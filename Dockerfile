# One image: Mini App static files + HTTP API + Telegram bot.
#   docker build -t buyer-crm .
#   docker run --env-file .env -p 8080:8080 buyer-crm

FROM node:22-alpine AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web/ ./
RUN npm run build

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    WEB_DIST=/app/web/dist \
    PORT=8080
WORKDIR /app/backend
COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/crm ./crm
COPY --from=web /web/dist /app/web/dist
RUN useradd --create-home --uid 10001 crm
USER crm
EXPOSE 8080
CMD ["python", "-m", "crm.server"]
