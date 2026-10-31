FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app

RUN pip config set global.index-url https://mirrors.cloud.tencent.com/pypi/simple \
    && pip config set global.trusted-host mirrors.cloud.tencent.com

COPY requirements.txt ./
RUN pip install --upgrade pip && pip install -r requirements.txt

COPY . .

# Anonymous per-visitor databases live outside the source tree.
ENV XINJI_VISITOR_ISOLATION=1 \
    XINJI_VISITOR_DIR=/data/visitors

EXPOSE 80
CMD exec uvicorn server.main:app --host 0.0.0.0 --port 80 \
    --proxy-headers --forwarded-allow-ips="*"
