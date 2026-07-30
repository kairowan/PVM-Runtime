FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/server/src

RUN addgroup --system pvm \
    && adduser --system --ingroup pvm pvm \
    && mkdir -p /var/lib/pvm/repository /var/log/pvm \
    && chown -R pvm:pvm /var/lib/pvm /var/log/pvm

WORKDIR /app
COPY server/src /app/server/src

USER pvm
EXPOSE 8080
VOLUME ["/var/lib/pvm", "/var/log/pvm"]
HEALTHCHECK --interval=30s --timeout=3s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/readyz', timeout=2)"]

CMD ["python", "-m", "pvm_server.serve", "--repository", "/var/lib/pvm/repository", "--host", "0.0.0.0", "--port", "8080", "--audit-log", "/var/log/pvm/audit.jsonl"]
