FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONUTF8=1 MAKS_BIND=0.0.0.0 MAKS_DB_PATH=/data/maks.sqlite3 MAKS_VAULT_KEY_FILE=/data/vault.key
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt && useradd --uid 10001 --create-home maks && mkdir /data && chown maks:maks /data
COPY backend ./backend
COPY frontend ./frontend
COPY templates ./templates
COPY scripts/deliver_max_notifications.py ./scripts/deliver_max_notifications.py
USER maks
EXPOSE 8765 8767
ENTRYPOINT ["python", "backend/container_start.py"]
CMD ["--site", "school", "--port", "8765"]
