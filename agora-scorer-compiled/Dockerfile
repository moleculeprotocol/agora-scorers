FROM python:3.11.9-slim

LABEL org.opencontainers.image.source="https://github.com/moleculeprotocol/agora-scorers" \
      org.opencontainers.image.description="Agora official compiled deterministic scorer runtime" \
      org.opencontainers.image.url="https://github.com/moleculeprotocol/agora-scorers/tree/main/agora-scorer-compiled" \
      org.opencontainers.image.licenses="MIT"

WORKDIR /app

COPY common /app/common
COPY agora-scorer-compiled /app/agora-scorer-compiled

ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app/common:/app/agora-scorer-compiled:/app/agora-scorer-compiled/sdk

CMD ["python", "/app/agora-scorer-compiled/entrypoint.py"]
