# Database service: owns the SQLite volume. On start it creates the schema and seeds
# demo data (idempotent), then stays up so dependants can wait on its healthcheck.
FROM python:3.12-slim
WORKDIR /srv
ENV PYTHONUNBUFFERED=1 DATABASE_PATH=/data/erp.db
RUN pip install --no-cache-dir pyjwt
COPY backend/app ./app
RUN mkdir -p /data
VOLUME /data
HEALTHCHECK --interval=5s --timeout=3s --retries=10 CMD test -s /data/erp.db
CMD ["sh", "-c", "python -m app.seed && exec tail -f /dev/null"]
