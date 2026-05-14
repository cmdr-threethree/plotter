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
ENV PLOTTER_META="/app/data/meta.json"
ENV PORT=5000

# Create data directory for persistence
RUN mkdir -p /app/data

# Default command runs the web application
CMD ["python", "webapp/app.py"]
