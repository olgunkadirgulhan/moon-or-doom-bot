FROM python:3.12-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 TZ=Europe/Istanbul
COPY requirements.txt .
RUN pip install --no-cache-dir -q -r requirements.txt
COPY bot ./bot
COPY core ./core
COPY config ./config
VOLUME /app/data
CMD ["python", "-m", "bot.main"]
