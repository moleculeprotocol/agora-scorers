FROM python:3.11.9-slim

LABEL org.opencontainers.image.source="https://github.com/andymolecule/Agora" \
      org.opencontainers.image.url="https://github.com/andymolecule/agora-scorers/tree/main/agora-scorer-artifact-compare" \
      org.opencontainers.image.title="Agora Repro Scorer" \
      org.opencontainers.image.description="Deterministic exact-match scorer for CSV and JSON reproducibility-style presets."

WORKDIR /app
COPY common /app/common
COPY agora-scorer-artifact-compare /app/agora-scorer-artifact-compare
CMD ["python", "/app/agora-scorer-artifact-compare/score.py"]
