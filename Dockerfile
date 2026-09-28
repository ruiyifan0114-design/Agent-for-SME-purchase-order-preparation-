FROM node:22-alpine AS frontend
WORKDIR /ui
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim
WORKDIR /app
COPY requirements.lock ./
RUN pip install --no-cache-dir -r requirements.lock
COPY backend ./backend
COPY migrations ./migrations
COPY alembic.ini ./
COPY --from=frontend /ui/dist ./frontend/dist
COPY ["biz module", "./biz module"]
RUN useradd --create-home procurement
USER procurement
EXPOSE 8000
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn backend.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
