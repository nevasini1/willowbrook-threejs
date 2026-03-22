FROM python:3.11-slim

WORKDIR /app

# Install SQLite (included in slim but ensure dev headers are present)
RUN apt-get update && apt-get install -y --no-install-recommends \
    sqlite3 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Create directory for persistent SQLite data
RUN mkdir -p /app/data

VOLUME ["/app/data"]

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
