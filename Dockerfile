# build: docker build --no-cache --progress=plain --target=production --build-arg VERSION=x.y.z -t ghcr.io/tob1as/mcstatus-httpd:latest -f Dockerfile .
ARG DEBIAN_VERSION=13

FROM debian:${DEBIAN_VERSION}-slim AS build
# hadolint ignore=DL3008,DL3009
RUN apt-get update && \
    apt-get install --no-install-suggests --no-install-recommends --yes python3-venv gcc libpython3-dev && \
    python3 -m venv /venv && \
    /venv/bin/pip install --upgrade pip setuptools wheel


FROM build AS build-venv
COPY requirements.txt /app/requirements.txt
COPY mcstatus-httpd.py /app/mcstatus-httpd.py
RUN \
    #/venv/bin/pip install --no-cache-dir mcstatus && \
    /venv/bin/pip install --no-cache-dir --disable-pip-version-check -r /app/requirements.txt && \
    chmod +x /app/mcstatus-httpd.py && \
    # Default directory of the file caches (AVATAR_CACHE_DIR, PLAYER_UUID_CACHE_FILE), so a named volume gets the right owner.
    mkdir -p /cache/mcstatus-httpd/avatars


FROM gcr.io/distroless/python3-debian${DEBIAN_VERSION}:debug-nonroot AS debug

ARG BUILD_DATE
ARG VCS_REF
ARG VERSION

LABEL org.opencontainers.image.source="https://github.com/Tob1as/mcstatus-httpd"

# Version shown by the application (--version, /healthcheck, logs).
ENV MCSTATUS_HTTPD_VERSION=${VERSION}

COPY --from=build-venv /venv /venv
COPY --from=build-venv /app /app
COPY --from=build-venv --chown=nonroot:nonroot /cache/mcstatus-httpd /tmp/mcstatus-httpd

WORKDIR /app
#USER nonroot
STOPSIGNAL SIGINT
EXPOSE 8080
#HEALTHCHECK --interval=60s --timeout=5s --start-period=10s --retries=3 \
#    CMD ["/venv/bin/python3", "/app/mcstatus-httpd.py", "--healthcheck"]

ENTRYPOINT ["/venv/bin/python3"]
CMD ["-u", "./mcstatus-httpd.py"]


FROM gcr.io/distroless/python3-debian${DEBIAN_VERSION}:nonroot AS production

ARG BUILD_DATE
ARG VCS_REF
ARG DEBIAN_VERSION
ARG VERSION

LABEL org.opencontainers.image.authors="Tobias Hargesheimer <docker@ison.ws>" \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.created="${BUILD_DATE}" \
      org.opencontainers.image.revision="${VCS_REF}" \
      org.opencontainers.image.title="mcstatus-httpd" \
      org.opencontainers.image.description="Minecraft Server Status HTTPD (Distroless with Python3)" \
      org.opencontainers.image.documentation="https://github.com/Tob1as/mcstatus-httpd" \
      org.opencontainers.image.base.name="gcr.io/distroless/python3-debian${DEBIAN_VERSION}:nonroot" \
      org.opencontainers.image.licenses="Apache-2.0" \
      org.opencontainers.image.url="ghcr.io/tob1as/mcstatus-httpd:latest" \
      org.opencontainers.image.source="https://github.com/Tob1as/mcstatus-httpd"

# Version shown by the application (--version, /healthcheck, logs).
ENV MCSTATUS_HTTPD_VERSION=${VERSION}

COPY --from=build-venv /venv /venv
COPY --from=build-venv /app /app
COPY --from=build-venv --chown=nonroot:nonroot /cache/mcstatus-httpd /tmp/mcstatus-httpd

WORKDIR /app
#USER nonroot
STOPSIGNAL SIGINT
EXPOSE 8080
#HEALTHCHECK --interval=60s --timeout=5s --start-period=10s --retries=3 \
#	CMD ["/venv/bin/python3", "/app/mcstatus-httpd.py", "--healthcheck"]

ENTRYPOINT ["/venv/bin/python3"]
CMD ["-u", "./mcstatus-httpd.py"]