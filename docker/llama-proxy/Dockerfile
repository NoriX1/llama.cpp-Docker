FROM python:3.12-slim-bookworm

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/proxy

COPY config/llama-proxy.py /opt/proxy/llama-proxy.py
COPY scripts/llama-proxy-healthcheck.py /usr/local/bin/llama-proxy-healthcheck.py
COPY scripts/llama-proxy-entrypoint.sh /usr/local/bin/llama-proxy-entrypoint.sh

RUN chmod +x /opt/proxy/llama-proxy.py /usr/local/bin/llama-proxy-healthcheck.py /usr/local/bin/llama-proxy-entrypoint.sh

ENV PYTHONUNBUFFERED=1

EXPOSE 8000

HEALTHCHECK --interval=120s --timeout=5s --start-period=20s --retries=3 CMD ["/usr/local/bin/llama-proxy-healthcheck.py"]

CMD ["/usr/local/bin/llama-proxy-entrypoint.sh"]
