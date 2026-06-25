# ProofCheck production image — the FULL app, including the Tesseract OCR engine.
#
# Build:  docker build -t proofcheck:latest .
# Run:    docker run -p 8000:8000 -v proofcheck-data:/data proofcheck:latest
# See DEPLOYMENT.md for compose, volumes, env, and platform-specific guides.

FROM python:3.12-slim

# System dependency: the Tesseract OCR engine (+ English language data). Add more language
# packs as needed, e.g. `tesseract-ocr-ara tesseract-ocr-fra`, to match your --ocr-lang.
RUN apt-get update \
 && apt-get install -y --no-install-recommends tesseract-ocr \
 && rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    # Persist auth/history + the OCR cache under /data (mount a volume there).
    PROOFCHECK_DB=/data/proofcheck.db \
    PROOFCHECK_OCR_CACHE=/data/ocr_cache

WORKDIR /app

# Copy only what's needed to build/install the package (keeps the image small; the rest is
# excluded by .dockerignore).
COPY pyproject.toml README.md ./
COPY proofcheck ./proofcheck

# Install the app with the OCR extra (pytesseract / Pillow / pypdfium2). The Tesseract
# *binary* came from apt above.
RUN pip install ".[ocr]"

# Drop privileges; /data must be writable for the sqlite DB + OCR cache.
RUN useradd --create-home --uid 10001 appuser \
 && mkdir -p /data && chown -R appuser:appuser /data
USER appuser

EXPOSE 8000

# Liveness: the app's own health endpoint (also reports ocr_available).
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health').status==200 else 1)"

# One worker is fine to start. OCR is CPU-bound, so scale with more workers/replicas
# (e.g. add `--workers 4`) once you size the host. See DEPLOYMENT.md › Scaling.
CMD ["uvicorn", "proofcheck.web.app:app", "--host", "0.0.0.0", "--port", "8000"]
