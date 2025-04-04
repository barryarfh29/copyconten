FROM python:3.12-slim

WORKDIR /app

# Update apt-get and install required system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    python3-dev \
    ffmpeg && rm -rf /var/lib/apt/lists/*

# Copy and install requirements
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install setuptools --upgrade && \
    pip install --no-cache-dir -r requirements.txt

# Copy application code and configuration
COPY . .

CMD ["python", "main.py"]
