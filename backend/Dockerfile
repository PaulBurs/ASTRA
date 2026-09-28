FROM python:3.13-slim

WORKDIR /app

COPY backend/requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY data_pipeline /opt/data_pipeline
ENV PYTHONPATH=/opt/data_pipeline:/opt
COPY backend .
# The backend integration tests exercise the real ML reader in-process.
COPY ml/src /app/ml/src
COPY source_agent /app/source_agent

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
