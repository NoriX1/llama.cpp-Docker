#!/usr/bin/env python3
"""
Proxy for OpenClaw/OpenAI-compatible traffic in front of llama.cpp server.
"""

import ast
import http.server
import json
import logging
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request


LISTEN_HOST = os.environ.get("PROXY_HOST", "0.0.0.0")
LISTEN_PORT = int(os.environ.get("PROXY_PORT", "8000"))
BACKEND_URL = os.environ.get("BACKEND_URL", "http://llama-server:8001")
BACKEND_TIMEOUT = int(os.environ.get("BACKEND_TIMEOUT", "600"))
CHUNK_SIZE = 64 * 1024
THINK_KEYWORD = os.environ.get("THINK_KEYWORD", "[think]")
LOG_LEVEL = os.environ.get("PROXY_LOG_LEVEL", "INFO").upper()

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s [proxy] %(levelname)s %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger("llama-proxy")


def rewrite_messages(messages):
    if not isinstance(messages, list):
        return messages

    for msg in messages:
        if not isinstance(msg, dict):
            continue
        role = msg.get("role")
        if role == "developer":
            msg["role"] = "system"
            log.info("Rewrote role: developer -> system")
        elif role == "toolResult":
            msg["role"] = "tool"
            log.info("Rewrote role: toolResult -> tool")

    first_system_idx = next(
        (i for i, m in enumerate(messages) if isinstance(m, dict) and m.get("role") == "system"),
        None,
    )
    out = []
    for i, msg in enumerate(messages):
        if not isinstance(msg, dict):
            out.append(msg)
            continue
        if msg.get("role") == "system" and i != first_system_idx and first_system_idx is not None:
            first_content = messages[first_system_idx].get("content") or ""
            extra = msg.get("content") or ""
            messages[first_system_idx]["content"] = (first_content + "\n\n" + extra).strip()
            log.info("Merged mid-conversation system message into first system message")
            continue
        out.append(msg)
    return out


def check_and_strip_think_keyword(messages):
    if not isinstance(messages, list):
        return False
    for msg in reversed(messages):
        if isinstance(msg, dict) and msg.get("role") == "user":
            content = msg.get("content") or ""
            if isinstance(content, str) and content.lstrip().lower().startswith(THINK_KEYWORD):
                msg["content"] = content.lstrip()[len(THINK_KEYWORD):].lstrip()
                log.info("Detected [think] keyword; enabling thinking mode")
                return True
            break
    return False


def extract_text_from_openclaw_content(content):
    if not isinstance(content, str):
        return content

    if content.startswith("[") or content.startswith("{"):
        for loader in (json.loads, ast.literal_eval):
            try:
                parsed = loader(content)
            except Exception:
                continue

            if isinstance(parsed, list):
                texts = []
                for item in parsed:
                    if isinstance(item, dict) and "text" in item:
                        texts.append(item["text"])
                return "\n".join(texts) if texts else content
            if isinstance(parsed, dict) and "text" in parsed:
                return parsed["text"]

    return content


def convert_openclaw_tool_calls_to_qwen(content):
    if not isinstance(content, str):
        return content

    if "<function=" not in content and "<function>" not in content:
        return content

    func_pattern = re.compile(r"<function=(\w+)>\s*(.*?)\s*</function>\s*</tool_call>", re.DOTALL)
    matches = list(func_pattern.finditer(content))

    if not matches:
        func_pattern = re.compile(r"<function>(\w+)</function>\s*(.*?)\s*</tool_call>", re.DOTALL)
        matches = list(func_pattern.finditer(content))
        if not matches:
            return content

    result = content
    for match in reversed(matches):
        func_name = match.group(1)
        param_content = match.group(2)
        params_dict = {}

        param_pattern = re.compile(r"<parameter>(\w+)>([^<]*)</parameter>", re.DOTALL)
        for param_match in param_pattern.finditer(param_content):
            params_dict[param_match.group(1)] = param_match.group(2).strip()

        if not params_dict:
            param_pattern = re.compile(r"<parameter>(\w+)=([^<]+)</parameter>", re.DOTALL)
            for param_match in param_pattern.finditer(param_content):
                params_dict[param_match.group(1)] = param_match.group(2).strip()

        qwen_format = {
            "name": func_name,
            "arguments": params_dict,
        }
        replacement = "<tool_call>\n" + json.dumps(qwen_format, ensure_ascii=False) + "\n</tool_call>"
        result = result[: match.start()] + replacement + result[match.end() :]

    return result


def convert_qwen_tool_calls_to_openclaw(content):
    if not isinstance(content, str):
        return content

    if "<tool_call>" not in content or "<function=" in content or "<function>" in content:
        return content

    qwen_pattern = re.compile(r"<tool_call>\s*(\{.*?\})\s*</tool_call>", re.DOTALL)
    match = qwen_pattern.search(content)
    if not match:
        return content

    try:
        tool_call_json = json.loads(match.group(1))
    except json.JSONDecodeError:
        return content

    func_name = tool_call_json.get("name", "unknown")
    args = tool_call_json.get("arguments", {})

    result = f"<function={func_name}>"
    for key, value in args.items():
        result += f"<parameter>{key}>\n{value}\n</parameter>"
    result += "</function>\n</tool_call>"
    return result


def convert_response_for_openclaw(content):
    if not isinstance(content, str):
        return content
    content = convert_qwen_tool_calls_to_openclaw(content)
    return extract_text_from_openclaw_content(content)


def rewrite_body(obj):
    if not (isinstance(obj, dict) and "messages" in obj):
        return obj

    thinking = check_and_strip_think_keyword(obj["messages"])
    obj["messages"] = rewrite_messages(obj["messages"])

    for msg in obj["messages"]:
        if isinstance(msg, dict) and "content" in msg and isinstance(msg["content"], str):
            msg["content"] = extract_text_from_openclaw_content(msg["content"])
            msg["content"] = convert_openclaw_tool_calls_to_qwen(msg["content"])

    kwargs = obj.setdefault("chat_template_kwargs", {})
    if thinking:
        kwargs["enable_thinking"] = True
    elif "enable_thinking" not in kwargs:
        kwargs["enable_thinking"] = False

    return obj


def backend_health():
    try:
        with urllib.request.urlopen(BACKEND_URL + "/health", timeout=5) as response:
            payload = json.loads(response.read().decode("utf-8"))
            return response.status == 200 and payload.get("status") == "ok"
    except Exception:
        return False


class ProxyHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        log.info(fmt, *args)

    def _send_json(self, code, payload):
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(raw)

    def _read_body(self):
        content_length_hdr = self.headers.get("Content-Length")
        transfer_encoding = self.headers.get("Transfer-Encoding", "").lower()

        if content_length_hdr is not None:
            return self.rfile.read(int(content_length_hdr))

        if "chunked" in transfer_encoding:
            chunks = []
            while True:
                size_line = self.rfile.readline().strip()
                if not size_line:
                    break
                chunk_size = int(size_line, 16)
                if chunk_size == 0:
                    self.rfile.readline()
                    break
                chunk = self.rfile.read(chunk_size)
                self.rfile.read(2)
                chunks.append(chunk)
            return b"".join(chunks)

        return b""

    def do_request(self, method):
        if self.path == "/health":
            status = backend_health()
            self._send_json(200 if status else 503, {"status": "ok" if status else "degraded"})
            return

        body = self._read_body()
        content_type = self.headers.get("Content-Type", "")
        if body and "application/json" in content_type:
            try:
                parsed = json.loads(body)
                if "messages" in parsed:
                    roles = [m.get("role") for m in parsed["messages"]]
                    log.info("Roles in request: %s", roles)
                body = json.dumps(rewrite_body(parsed)).encode("utf-8")
            except Exception as exc:
                log.warning("Could not parse or rewrite JSON body: %s", exc)

        target_url = urllib.parse.urljoin(BACKEND_URL.rstrip("/") + "/", self.path.lstrip("/"))
        req = urllib.request.Request(target_url, data=body if body else None, method=method)
        skip_headers = {"host", "content-length", "transfer-encoding", "connection"}
        for key, value in self.headers.items():
            if key.lower() not in skip_headers:
                req.add_header(key, value)
        if body:
            req.add_header("Content-Length", str(len(body)))

        try:
            with urllib.request.urlopen(req, timeout=BACKEND_TIMEOUT) as resp:
                response_body = resp.read()
                self.send_response(resp.status)
                for key, value in resp.headers.items():
                    if key.lower() not in {"transfer-encoding", "connection", "content-length"}:
                        self.send_header(key, value)

                rewritten_body = self._rewrite_backend_response(response_body)
                self.send_header("Content-Length", str(len(rewritten_body)))
                self.end_headers()
                if self.command != "HEAD":
                    self.wfile.write(rewritten_body)

        except urllib.error.HTTPError as exc:
            raw = exc.read()
            self.send_response(exc.code)
            for key, value in exc.headers.items():
                if key.lower() not in {"transfer-encoding", "connection", "content-length"}:
                    self.send_header(key, value)
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(raw)
        except Exception as exc:
            log.error("Proxy error: %s", exc)
            self._send_json(502, {"error": f"Proxy error: {exc}"})

    def _rewrite_backend_response(self, response_body):
        try:
            response_str = response_body.decode("utf-8")
        except UnicodeDecodeError:
            return response_body

        lines = response_str.split("\n")
        result_lines = []
        for line in lines:
            if not line.startswith("data: "):
                result_lines.append(line)
                continue

            data = line[6:]
            if data.strip() == "[DONE]":
                result_lines.append(line)
                continue

            try:
                parsed = json.loads(data)
            except json.JSONDecodeError:
                result_lines.append(line)
                continue

            if "choices" in parsed and parsed["choices"]:
                for choice in parsed["choices"]:
                    if "message" in choice and "tool_calls" in choice["message"]:
                        for tool_call in choice["message"]["tool_calls"] or []:
                            function = tool_call.get("function", {})
                            args = function.get("arguments")
                            if isinstance(args, dict):
                                content = f"<function={function.get('name', 'unknown')}>"
                                for key, value in args.items():
                                    content += f"<parameter>{key}>\n{value}\n</parameter>"
                                content += "</function>\n</tool_call>"
                                choice["message"]["content"] = content
                                choice["message"]["tool_calls"] = None

                    if "delta" in choice and "content" in choice["delta"] and choice["delta"]["content"]:
                        choice["delta"]["content"] = convert_response_for_openclaw(choice["delta"]["content"])
                    elif "message" in choice and "content" in choice["message"] and choice["message"]["content"]:
                        choice["message"]["content"] = convert_response_for_openclaw(choice["message"]["content"])

            result_lines.append("data: " + json.dumps(parsed, ensure_ascii=False))

        return "\n".join(result_lines).encode("utf-8")

    def do_GET(self):
        self.do_request("GET")

    def do_POST(self):
        self.do_request("POST")

    def do_PUT(self):
        self.do_request("PUT")

    def do_DELETE(self):
        self.do_request("DELETE")

    def do_OPTIONS(self):
        self.do_request("OPTIONS")

    def do_HEAD(self):
        self.do_request("HEAD")


class ThreadedHTTPServer(http.server.ThreadingHTTPServer):
    daemon_threads = True


if __name__ == "__main__":
    server = ThreadedHTTPServer((LISTEN_HOST, LISTEN_PORT), ProxyHandler)
    log.info("llama-proxy listening on %s:%d -> %s", LISTEN_HOST, LISTEN_PORT, BACKEND_URL)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log.info("Shutting down")
        server.shutdown()
