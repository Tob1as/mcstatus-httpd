FROM python:3.14-alpine AS production

ARG BUILD_DATE
ARG VCS_REF

LABEL org.opencontainers.image.authors="Tobias Hargesheimer <docker@ison.ws>" \
	#org.opencontainers.image.version="${VCS_REF}" \
	org.opencontainers.image.created="${BUILD_DATE}" \
	org.opencontainers.image.revision="${VCS_REF}" \
	org.opencontainers.image.title="mcstatus-httpd" \
	org.opencontainers.image.description="Minecraft Server Status HTTPD (AlpineLinux with Python3)" \
	org.opencontainers.image.documentation="https://github.com/Tob1as/mcstatus-httpd" \
	org.opencontainers.image.base.name="docker.io/library/python:3.14-alpine" \
	org.opencontainers.image.licenses="Apache-2.0" \
	org.opencontainers.image.url="ghcr.io/tob1as/mcstatus-httpd:latest" \
	org.opencontainers.image.source="https://github.com/Tob1as/mcstatus-httpd"

SHELL ["/bin/sh", "-euxo", "pipefail", "-c"]

COPY requirements.txt /app/requirements.txt
COPY mcstatus-httpd.py /app/mcstatus-httpd.py

RUN \
    #pip install --no-cache-dir mcstatus ; \
	pip install --disable-pip-version-check -r /app/requirements.txt ; \
	chmod +x /app/mcstatus-httpd.py

WORKDIR /app
USER nobody
STOPSIGNAL SIGINT
EXPOSE 8080

ENTRYPOINT ["/usr/local/bin/python3"]
CMD ["-u", "./mcstatus-httpd.py"]