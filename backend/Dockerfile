FROM python:3.12-slim
WORKDIR /srv
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 \
    # Make the app and the supplier_packing_list integration package importable (both live under /srv).
    PYTHONPATH=/srv \
    # Docling model caches live on a mounted volume (see docker-compose.yml) so they
    # download once and survive restarts. The isolated PDF worker inherits these.
    HF_HOME=/models/huggingface \
    EASYOCR_MODULE_PATH=/models/easyocr

# Native libraries Docling's PDF parsing / OCR need at runtime.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
COPY supplier_packing_list ./supplier_packing_list
RUN mkdir -p /models
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --retries=5 CMD python -c "import urllib.request;urllib.request.urlopen('http://localhost:8000/health')"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
