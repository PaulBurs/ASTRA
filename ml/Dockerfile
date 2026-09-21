FROM python:3.13-slim

WORKDIR /app

COPY requirements.txt /tmp/ml-requirements.txt

RUN pip install \
    --no-cache-dir \
    -r /tmp/ml-requirements.txt

COPY . /app/ml

EXPOSE 9000

CMD ["python", "-m", "uvicorn", "ml.src.api:app", "--host", "0.0.0.0", "--port", "9000"]
