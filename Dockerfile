# Dockerfile for the Geospatial Microservice

# ---- STAGE 1: The "Builder" Stage ----
# We use a full version of Python here because installing geospatial libraries
# sometimes requires extra build tools that are included in this larger image.
# We name this stage "builder" so we can refer to it later.
FROM python:3.9 as builder

# Set the working directory inside the container. It's like running `cd /app`.
WORKDIR /app

# Copy ONLY the requirements file first.
# This is a Docker optimization. If this file doesn't change, Docker can
# reuse the cached layer below, making future builds much faster.
COPY requirements.txt .

# Run the pip install command to download and install all your heavy libraries.
# --no-cache-dir helps keep the image a little smaller.
RUN pip install --no-cache-dir -r requirements.txt


# ---- STAGE 2: The "Final" Stage ----
# Now, we start fresh with a much smaller "slim" Python image.
# This keeps our final container lightweight.
FROM python:3.9-slim


RUN apt-get update && apt-get install -y libexpat1 && rm -rf /var/lib/apt/lists/*

# Set the same working directory.
WORKDIR /app

# This is the magic of the multi-stage build:
# We copy ONLY the installed packages from our "builder" stage into this
# clean, slim image. We don't bring along any of the temporary build tools.
COPY --from=builder /usr/local/lib/python3.9/site-packages /usr/local/lib/python3.9/site-packages

# --- THIS IS THE NEW, CRITICAL LINE ---
# Copy the executable programs (like gunicorn) from the builder stage
COPY --from=builder /usr/local/bin /usr/local/bin

# Now, copy your application code and data into the final image.
COPY main.py .
COPY ./data ./data

# This is the command that will be executed when your container starts on Cloud Run.
# We use Gunicorn, a production-ready web server, instead of Flask's basic one.
# - Gunicorn listens on all network interfaces (`0.0.0.0`) on the port
#   that Cloud Run provides via the `$PORT` environment variable.
# - `main:app` tells Gunicorn to run the `app` object found in the `main.py` file.
# - `--timeout 0` prevents Gunicorn from killing a worker on a slow request,
#   which is useful in a serverless environment with cold starts.
CMD gunicorn --bind 0.0.0.0:$PORT --workers 1 --threads 8 --timeout 0 main:app