FROM python:3.13-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8051

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py data_update.py extract_series.py extract_regional.py ./
COPY assets ./assets
COPY data ./data
RUN mkdir -p pnad

EXPOSE 8051

CMD ["sh", "-c", "gunicorn app:server --bind 0.0.0.0:${PORT:-8051} --workers 1 --threads 4 --timeout 300"]
