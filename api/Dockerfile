FROM python:3.12-slim
WORKDIR /app
COPY api/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY src/extract.py api/main.py api/db.py api/storage.py api/auth.py api/jobs.py api/billing.py ./
ENV DATA_DIR=/data COOKIE_SECURE=1
RUN mkdir -p /data
EXPOSE 8080
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
