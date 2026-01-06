# We use 'bullseye' because it is the stable, rock-solid version of Linux
FROM python:3.9-slim-bullseye

# Install system dependencies
# We added 'fix-missing' to prevent network errors during download
RUN apt-get update --fix-missing && apt-get install -y \
    build-essential \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY . .

# Install python dependencies
RUN pip3 install --no-cache-dir -r requirements.txt

# Run the app
CMD streamlit run app.py --server.port $PORT --server.address 0.0.0.0
