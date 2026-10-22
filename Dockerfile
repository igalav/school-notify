# Chromium and its system libraries come with the base image (Galim needs a browser to log in).
FROM mcr.microsoft.com/playwright/python:v1.63.0-noble
WORKDIR /app
COPY school_notify school_notify
ENV SCHOOL_NOTIFY_DATA=/data PYTHONUNBUFFERED=1
VOLUME ["/data"]
CMD ["python", "-m", "school_notify", "run"]
