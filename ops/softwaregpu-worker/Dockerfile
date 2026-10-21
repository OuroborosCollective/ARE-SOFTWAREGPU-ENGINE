# Optional, private CPU renderer. This image is never published by the PR.
FROM python:3.12-slim-bookworm
ARG ARE_SOURCE_SHA
LABEL org.ouroboros.service="are-softwaregpu-worker" \
      org.opencontainers.image.revision="${ARE_SOURCE_SHA}"
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    OMP_NUM_THREADS=3 \
    OPENBLAS_NUM_THREADS=3 \
    MKL_NUM_THREADS=3 \
    NUMEXPR_NUM_THREADS=3
WORKDIR /app
COPY setup.py main.py ./
COPY software_gpu/ ./software_gpu/
COPY plugins/ ./plugins/
COPY fixtures/aurion/phase4_offline/job.example.json ./fixtures/aurion/phase4_offline/job.example.json
RUN python -m pip install --no-cache-dir ".[gradio-arena]" \
    && python -m unittest software_gpu.tests.test_gradio_arena -v \
    && groupadd --gid 10001 areworker \
    && useradd --uid 10001 --gid 10001 --no-create-home --home-dir /tmp --shell /usr/sbin/nologin areworker
USER 10001:10001
EXPOSE 7860
CMD ["python", "-m", "plugins.gradio_arena.app"]
