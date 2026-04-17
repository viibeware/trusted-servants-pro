FROM python:3.12-slim

WORKDIR /srv

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY run.py .

ENV FLASK_APP=run.py \
    PYTHONUNBUFFERED=1 \
    TSP_DATA_DIR=/data \
    TSP_UPLOAD_DIR=/data/uploads

RUN mkdir -p /data/uploads

EXPOSE 8000

CMD ["gunicorn", "-b", "0.0.0.0:8000", "-w", "2", "--timeout", "120", "--access-logfile", "-", "run:app"]
