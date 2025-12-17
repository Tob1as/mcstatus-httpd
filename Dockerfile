# build: docker build --no-cache --progress=plain --target=production -t ghcr.io/tob1as/mcstatus-httpd:latest -f Dockerfile .
ARG DEBIAN_VERSION=12

FROM debian:${DEBIAN_VERSION}-slim AS build
RUN apt-get update && \
    apt-get install --no-install-suggests --no-install-recommends --yes python3-venv gcc libpython3-dev && \
    python3 -m venv /venv && \
    /venv/bin/pip install --upgrade pip setuptools wheel


FROM build AS build-venv
COPY requirements.txt /app/requirements.txt
COPY mcstatus-httpd.py /app/mcstatus-httpd.py
RUN \
	#/venv/bin/pip install --no-cache-dir mcstatus && \
	/venv/bin/pip install --disable-pip-version-check -r /app/requirements.txt && \
	chmod +x /app/mcstatus-httpd.py


FROM gcr.io/distroless/python3-debian${DEBIAN_VERSION}:debug-nonroot AS debug

ARG BUILD_DATE
ARG VCS_REF

LABEL org.opencontainers.image.source="https://github.com/Tob1as/mcstatus-httpd"

COPY --from=build-venv /venv /venv
COPY --from=build-venv /app /app

WORKDIR /app
#USER nonroot
STOPSIGNAL SIGINT
EXPOSE 8080

ENTRYPOINT ["/venv/bin/python3"]
CMD ["-u", "./mcstatus-httpd.py"]


FROM gcr.io/distroless/python3-debian${DEBIAN_VERSION}:nonroot AS production

ARG BUILD_DATE
ARG VCS_REF
ARG DEBIAN_VERSION

LABEL org.opencontainers.image.authors="Tobias Hargesheimer <docker@ison.ws>" \
	#org.opencontainers.image.version="${VCS_REF}" \
	org.opencontainers.image.created="${BUILD_DATE}" \
	org.opencontainers.image.revision="${VCS_REF}" \
	org.opencontainers.image.title="mcstatus-httpd" \
	org.opencontainers.image.description="Minecraft Server Status HTTPD (Distroless with Python3)" \
	org.opencontainers.image.documentation="https://github.com/Tob1as/mcstatus-httpd" \
	org.opencontainers.image.base.name="gcr.io/distroless/python3-debian${DEBIAN_VERSION}:nonroot" \
	org.opencontainers.image.licenses="Apache-2.0" \
	org.opencontainers.image.url="ghcr.io/tob1as/mcstatus-httpd:latest" \
	org.opencontainers.image.source="https://github.com/Tob1as/mcstatus-httpd"

COPY --from=build-venv /venv /venv
COPY --from=build-venv /app /app

WORKDIR /app
#USER nonroot
STOPSIGNAL SIGINT
EXPOSE 8080

ENTRYPOINT ["/venv/bin/python3"]
CMD ["-u", "./mcstatus-httpd.py"]