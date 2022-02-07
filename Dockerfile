FROM python:3.10-alpine

LABEL org.opencontainers.image.authors="Tobias Hargesheimer <docker@ison.ws>" \
	#org.opencontainers.image.version="${VCS_REF}" \
	org.opencontainers.image.created="${BUILD_DATE}" \
	org.opencontainers.image.revision="${VCS_REF}" \
	org.opencontainers.image.title="mcstatus-httpd" \
	org.opencontainers.image.description="Minecraft Server Status HTTPD (AlpineLinux with Python3)" \
	org.opencontainers.image.licenses="Apache-2.0" \
	org.opencontainers.image.url="ghcr.io/tob1as/mcstatus-httpd:latest" \
	org.opencontainers.image.source="https://github.com/Tob1as/mcstatus-httpd"

SHELL ["/bin/sh", "-euxo", "pipefail", "-c"]

COPY mcstatus-httpd.py /service/mcstatus-httpd.py

RUN \
    addgroup --gid 1000 minecraft ; \
    adduser --system --shell /bin/sh --uid 1000 --ingroup minecraft --home /service minecraft ; \
    pip3 install --no-cache-dir mcstatus ; \
	chown minecraft:minecraft /service/mcstatus-httpd.py ; \
	chmod +x /service/mcstatus-httpd.py

WORKDIR /service
USER minecraft
STOPSIGNAL SIGINT
EXPOSE 8080

CMD ["python3", "-u", "./mcstatus-httpd.py"]