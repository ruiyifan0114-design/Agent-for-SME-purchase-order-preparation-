FROM python:3.12-slim
WORKDIR /app
COPY requirements.lock ./
RUN pip install --no-cache-dir -r requirements.lock
COPY backend ./backend
COPY migrations ./migrations
COPY alembic.ini ./
COPY ["biz module", "./biz module"]
RUN useradd --create-home procurement
USER procurement
EXPOSE 8000
CMD ["sh", "-c", "alembic upgrade head && uvicorn backend.main:app --host 0.0.0.0 --port 8000"]
