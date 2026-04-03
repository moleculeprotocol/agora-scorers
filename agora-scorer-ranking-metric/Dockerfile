FROM python:3.11-slim

LABEL org.opencontainers.image.source="https://github.com/andymolecule/Agora" \
      org.opencontainers.image.url="https://github.com/andymolecule/agora-scorers/tree/main/agora-scorer-ranking-metric" \
      org.opencontainers.image.title="Agora Docking Scorer" \
      org.opencontainers.image.description="Deterministic docking scorer image family for Agora docking presets."

WORKDIR /app
COPY common /app/common
COPY agora-scorer-ranking-metric /app/agora-scorer-ranking-metric
CMD ["python", "/app/agora-scorer-ranking-metric/score.py"]
