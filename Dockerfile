FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt gunicorn

# Copy application files
COPY app.py .
COPY feeds.opml .
COPY static/ static/

# Create data directory for database
RUN mkdir -p /data

# Environment variables
ENV RSS_DB=/data/rss.db
ENV RSS_PORT=8787
ENV FLASK_APP=app.py

# Expose port
EXPOSE 8787

# Run with gunicorn for production
CMD ["gunicorn", "--bind", "0.0.0.0:8787", "--workers", "2", "--timeout", "120", "--worker-class", "sync", "app:app"]
