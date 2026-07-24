# Container for the always-on interactivity bot (Slack Socket Mode).
# Build from the REPO ROOT so both src/ and interactivity/ are in context:
#   docker build -f interactivity/Dockerfile -t finance-tracker-bot .
FROM python:3.12-slim

WORKDIR /app

# Deps first for layer caching.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Shared pipeline code + the bot. app.py puts ../src on sys.path at runtime.
COPY src/ ./src/
COPY interactivity/ ./interactivity/

# Cloud Run injects $PORT; the health server binds it (config.HEALTH_PORT).
ENV PORT=8080
EXPOSE 8080

CMD ["python", "interactivity/app.py"]
