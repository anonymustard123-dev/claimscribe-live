# Use the stable version of Linux
FROM python:3.9-slim-bullseye

# Install system dependencies
RUN apt-get update --fix-missing && apt-get install -y \
    build-essential \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY . .

# Install python dependencies
RUN pip3 install --no-cache-dir -r requirements.txt

# --- THE FIX: FORCE PORT 8080 ---
EXPOSE 8080
CMD streamlit run app.py --server.port 8080 --server.address 0.0.0.0
