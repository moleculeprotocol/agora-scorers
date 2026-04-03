FROM python:3.11.9-slim

LABEL org.opencontainers.image.source="https://github.com/andymolecule/Agora" \
      org.opencontainers.image.url="https://github.com/andymolecule/agora-scorers/tree/main/agora-scorer-python-execution" \
      org.opencontainers.image.title="Agora Code Executor" \
      org.opencontainers.image.description="Deterministic Python code execution scorer for Agora pass-rate challenges."

WORKDIR /app
COPY common /app/common
COPY agora-scorer-python-execution /app/agora-scorer-python-execution
CMD ["python", "/app/agora-scorer-python-execution/score.py"]
