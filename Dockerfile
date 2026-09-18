FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 ANTON_DB_PATH=/data/anton.db
WORKDIR /app
COPY pyproject.toml requirements.lock ./
COPY anton ./anton
RUN pip install --no-cache-dir --constraint requirements.lock . && mkdir -p /data
EXPOSE 8000
CMD ["sh", "-c", "exec uvicorn anton.main:app --host 0.0.0.0 --port ${PORT:-8000} --no-access-log"]
