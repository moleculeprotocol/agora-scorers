FROM python:3.11.9-slim@sha256:8fb099199b9f2d70342674bd9dbccd3ed03a258f26bbd1d556822c6dfc60c317

LABEL org.opencontainers.image.source="https://github.com/moleculeprotocol/agora-scorers" \
      org.opencontainers.image.description="Agora RDKit Python deterministic scorer runtime" \
      org.opencontainers.image.url="https://github.com/moleculeprotocol/agora-scorers/tree/main/agora-scorer-rdkit" \
      org.opencontainers.image.licenses="MIT" \
      agora.runtime-profile-id="rdkit_python_runtime" \
      agora.base-image="python:3.11.9-slim@sha256:8fb099199b9f2d70342674bd9dbccd3ed03a258f26bbd1d556822c6dfc60c317" \
      agora.python-package.rdkit="2025.3.1" \
      agora.python-package.numpy="2.4.4" \
      agora.python-package.pillow="12.2.0"

WORKDIR /app

COPY agora-scorer-rdkit/requirements.txt /tmp/agora-scorer-rdkit-requirements.txt
RUN python -m pip install \
      --disable-pip-version-check \
      --no-cache-dir \
      --only-binary=:all: \
      --require-hashes \
      -r /tmp/agora-scorer-rdkit-requirements.txt \
    && rm /tmp/agora-scorer-rdkit-requirements.txt

COPY common /app/common
COPY agora-scorer-compiled /app/agora-scorer-compiled

ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app/common:/app/agora-scorer-compiled

CMD ["python", "/app/agora-scorer-compiled/entrypoint.py"]
