FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HEALTH_PORT=8080

WORKDIR /app
COPY business_media_bot.py /app/business_media_bot.py

USER 65534:65534
EXPOSE 8080
CMD ["python", "business_media_bot.py"]
