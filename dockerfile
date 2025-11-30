# Use a lightweight Python image
FROM python:3.11-slim

# Set a working directory
WORKDIR /app

# System deps (add libmagic etc. if your file parsers need it)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first (better Docker cache)
COPY requirements.txt ./requirements.txt

# Install Python deps
RUN pip install --no-cache-dir -r requirements.txt

# Now copy the rest of the app
COPY . .

# Streamlit config to listen on 0.0.0.0
ENV STREAMLIT_SERVER_ADDRESS=0.0.0.0
ENV STREAMLIT_SERVER_PORT=8080

# You will set GOOGLE_API_KEY at deploy time in Cloud Run (not baked into image)
# ENV GOOGLE_API_KEY=...

# Expose port Cloud Run expects
EXPOSE 8080

# Default command: run Streamlit app
CMD ["streamlit", "run", "web_app.py", "--server.port=8080", "--server.address=0.0.0.0"]
