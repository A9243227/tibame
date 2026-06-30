FROM python:3.13-slim

WORKDIR /app

# BigQuery 轉換專屬的需求套件
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt google-cloud-bigquery

COPY src/ /app/src/

ENV PYTHONPATH="/app/src:${PYTHONPATH}"

CMD ["echo", "Please specify the BigQuery python script to run."]