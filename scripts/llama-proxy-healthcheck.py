#!/usr/bin/env python3
import json
import os
import sys
import urllib.error
import urllib.request


PORT = int(os.environ.get("PROXY_PORT", "8000"))
URL = f"http://127.0.0.1:{PORT}/health"

try:
    with urllib.request.urlopen(URL, timeout=5) as response:
        payload = json.loads(response.read().decode("utf-8"))
except (OSError, urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError) as exc:
    print(f"proxy healthcheck failed: {exc}", file=sys.stderr)
    sys.exit(1)

if payload.get("status") != "ok":
    print(f"unexpected proxy health payload: {payload}", file=sys.stderr)
    sys.exit(1)
