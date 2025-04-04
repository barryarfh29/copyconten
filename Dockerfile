FROM python:3.12-alpine

WORKDIR /app

# Update apk and install required system dependencies
RUN apk update && apk add --no-cache \
    python3-dev \
    gcc \
    musl-dev \
    ffmpeg

# Copy and install requirements
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy application code and configuration
COPY . .

CMD ["python", "main.py"]
