FROM python:3.12.9-slim

# Install build dependencies and curl
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Working directory
WORKDIR /app

# Copy requirements file and install dependencies
COPY requirements.txt requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
RUN sed -i 's/from numpy import NaN as npNaN/from numpy import nan as npNaN/' /usr/local/lib/python3.12/site-packages/pandas_ta/momentum/squeeze_pro.py
# Copy the rest of the project files
COPY . .

# Expose the server port
EXPOSE 8080

# Calculate the number of worker processes based on the number of CPU cores
CMD ["sh", "-c", "gunicorn -b 0.0.0.0:8080 --workers $(($(nproc --all) * 2 + 1)) app:app"]