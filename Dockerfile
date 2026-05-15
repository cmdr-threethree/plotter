# Use a lightweight Python image
FROM python:3.11-slim

# Set the working directory
WORKDIR /app

# Copy requirements and install them
COPY webapp/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application code
COPY . .

# Expose the port the app runs on
EXPOSE 5000

# Set environment variables for the webapp
# These point to /app/data so they can be mounted as volumes
ENV PLOTTER_DB="/app/data/systems.db"
ENV PORT=5000

# Create data directory for persistence
RUN mkdir -p /app/data

# Default command runs the web application using Gunicorn
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "1", "--threads", "8", "--worker-tmp-dir", "/dev/shm", "--access-logfile", "-", "--error-logfile", "-", "webapp.app:app"]
