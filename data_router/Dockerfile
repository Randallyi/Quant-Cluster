FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends tzdata && rm -rf /var/lib/apt/lists/* && \
    mkdir -p /usr/share/zoneinfo/US && \
    ln -sf /usr/share/zoneinfo/America/New_York /usr/share/zoneinfo/US/Eastern

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8888

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8888", "--loop", "asyncio"]
