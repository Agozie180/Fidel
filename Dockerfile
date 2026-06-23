FROM python:3.12-slim AS backend

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8000

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend ./backend
COPY config ./config
COPY data ./data

EXPOSE 8000

# Single worker keeps memory low; the agent is a stateful singleton so multiple
# workers would duplicate the trading loop. $PORT is provided by Railway.
CMD ["sh", "-c", "uvicorn backend.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1 --no-access-log"]
