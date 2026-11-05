FROM python:3.13-alpine AS production

ARG BUILD_DATE
ARG VCS_REF
ARG VERSION

LABEL org.opencontainers.image.authors="Tobias Hargesheimer <docker@ison.ws>" \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.created="${BUILD_DATE}" \
      org.opencontainers.image.revision="${VCS_REF}" \
      org.opencontainers.image.title="mcstatus-httpd" \
      org.opencontainers.image.description="Minecraft Server Status HTTPD (AlpineLinux with Python3)" \
      org.opencontainers.image.documentation="https://github.com/Tob1as/mcstatus-httpd" \
      org.opencontainers.image.base.name="docker.io/library/python:3.13-alpine" \
      org.opencontainers.image.licenses="Apache-2.0" \
      org.opencontainers.image.url="ghcr.io/tob1as/mcstatus-httpd:latest" \
      org.opencontainers.image.source="https://github.com/Tob1as/mcstatus-httpd"

# Version shown by the application (--version, /healthcheck, logs).
ENV MCSTATUS_HTTPD_VERSION=${VERSION}

SHELL ["/bin/sh", "-euxo", "pipefail", "-c"]

COPY requirements.txt /app/requirements.txt
COPY mcstatus-httpd.py /app/mcstatus-httpd.py

RUN \
    #pip install --no-cache-dir mcstatus ; \
    pip install --no-cache-dir --disable-pip-version-check -r /app/requirements.txt ; \
    chmod +x /app/mcstatus-httpd.py ; \
    # Default directory of the file caches (AVATAR_CACHE_DIR, PLAYER_UUID_CACHE_FILE), so a named volume gets the right owner.
    mkdir -p /tmp/mcstatus-httpd/avatars ; \
    chown -R nobody:nobody /tmp/mcstatus-httpd

WORKDIR /app
# User: nobody
USER 65534
STOPSIGNAL SIGINT
EXPOSE 8080
#HEALTHCHECK --interval=60s --timeout=5s --start-period=10s --retries=3 \
#    CMD ["/usr/local/bin/python3", "/app/mcstatus-httpd.py", "--healthcheck"]

ENTRYPOINT ["/usr/local/bin/python3"]
CMD ["-u", "./mcstatus-httpd.py"]