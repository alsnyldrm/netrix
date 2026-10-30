FROM node:22.20.0-bookworm-slim AS frontend
WORKDIR /build
COPY frontend/package*.json ./
RUN npm ci --ignore-scripts
COPY frontend/ ./
RUN npm run build

FROM redis:8.2.2-bookworm AS redis

FROM python:3.13.7-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/app/backend
WORKDIR /app
COPY requirements.txt requirements.lock ./
RUN apt-get update && apt-get install -y --no-install-recommends mariadb-client iputils-ping \
    && setcap -r /usr/bin/ping \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir -r requirements.lock \
    && groupadd -g 10001 netrix && useradd -u 10001 -g netrix -m netrix \
    && mkdir /data && chown netrix:netrix /data
COPY --from=redis /usr/local/bin/redis-server /usr/local/bin/redis-cli /usr/local/bin/
COPY --chown=10001:10001 backend/ /app/backend/
COPY --chown=10001:10001 deploy/supervisord.conf deploy/redis.conf /app/deploy/
COPY --from=frontend --chown=10001:10001 /build/dist /app/frontend/dist
USER netrix
EXPOSE 8000
CMD ["python","-m","netrix.runtime","start"]
