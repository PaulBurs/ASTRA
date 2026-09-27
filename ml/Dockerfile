FROM python:3.13-slim

WORKDIR /app

COPY ml/requirements.txt /tmp/ml-requirements.txt

RUN pip install \
    --no-cache-dir \
    -r /tmp/ml-requirements.txt

# LightGBM wheels dynamically link against the GNU OpenMP runtime.
RUN apt-get update \
    && apt-get install --no-install-recommends -y libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY data_pipeline /opt/data_pipeline
ENV PYTHONPATH=/opt/data_pipeline
COPY ml /app/ml

EXPOSE 9000

CMD ["python", "-m", "uvicorn", "ml.src.api:app", "--host", "0.0.0.0", "--port", "9000"]
