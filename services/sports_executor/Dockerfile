FROM python:3.12-slim-bookworm
RUN apt-get update && apt-get install -y --no-install-recommends bash ca-certificates git gh jq zip unzip curl \
    && rm -rf /var/lib/apt/lists/*
RUN python3 -m pip install --no-cache-dir numpy==2.2.6 PyYAML==6.0.2 pdfplumber==0.11.7
WORKDIR /opt/sports
COPY . /opt/sports
RUN useradd --uid 10001 --create-home executor && mkdir -p /var/lib/sports-executor \
    && chown executor:executor /var/lib/sports-executor
USER executor
ENV SPORTS_EXECUTOR_LIVE=0 PORT=8080 PYTHONDONTWRITEBYTECODE=1
EXPOSE 8080
CMD ["python3", "services/sports_executor/server.py"]
