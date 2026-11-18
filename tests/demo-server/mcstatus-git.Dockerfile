# Test image: the current mcstatus-httpd.py of this repository with mcstatus from GitHub
# (https://github.com/py-mine/mcstatus, default: main branch), to test unreleased mcstatus changes
# before they are released. Same layout as the production image of ../../Dockerfile (distroless,
# /venv, /app), only for testing. Keep the stages in sync with ../../Dockerfile.
#
# Used by docker-compose.mcstatus-git.yml (override for docker-compose.yml in this folder), see README.md.
#
# Build alone (from the repository root):
#   docker build -t local/mcstatus-httpd:mcstatus-git -f tests/demo-server/mcstatus-git.Dockerfile .
# Other branch, tag or commit of mcstatus: --build-arg MCSTATUS_REF=<branch|tag|commit>
# The mcstatus archive is downloaded with ADD, so Docker loads it again when the branch has changed.
# To be sure (e.g. after a long time) build without cache: --no-cache
# The build output shows the tested mcstatus commit (with --progress=plain).
#
# Note: mcstatus installed from GitHub reports the version 0.0.0 (log "mcstatus 0.0.0"), that is expected.
# requirements.txt is not used here (it would install the released mcstatus from PyPI).
ARG DEBIAN_VERSION=13

FROM debian:${DEBIAN_VERSION}-slim AS build
# hadolint ignore=DL3008,DL3009
RUN apt-get update && \
    apt-get install --no-install-suggests --no-install-recommends --yes python3-venv gcc libpython3-dev && \
    python3 -m venv /venv && \
    /venv/bin/pip install --upgrade pip setuptools wheel


FROM build AS build-venv
# Branch, tag or commit of https://github.com/py-mine/mcstatus
ARG MCSTATUS_REF=main
ADD https://github.com/py-mine/mcstatus/archive/${MCSTATUS_REF}.tar.gz /tmp/mcstatus.tar.gz
COPY mcstatus-httpd.py /app/mcstatus-httpd.py
RUN \
    # GitHub stores the commit of the archive in the tar header.
    /venv/bin/python3 -c "import tarfile; print('mcstatus ${MCSTATUS_REF} commit:', tarfile.open('/tmp/mcstatus.tar.gz').pax_headers.get('comment', 'unknown'))" && \
    /venv/bin/pip install --no-cache-dir --disable-pip-version-check /tmp/mcstatus.tar.gz && \
    rm /tmp/mcstatus.tar.gz && \
    /venv/bin/python3 -W error -m py_compile /app/mcstatus-httpd.py && \
    chmod +x /app/mcstatus-httpd.py && \
    mkdir -p /cache/mcstatus-httpd/avatars


FROM gcr.io/distroless/python3-debian${DEBIAN_VERSION}:nonroot AS production

ARG MCSTATUS_REF=main
LABEL org.opencontainers.image.title="mcstatus-httpd (mcstatus ${MCSTATUS_REF} test)" \
      org.opencontainers.image.description="mcstatus-httpd with mcstatus ${MCSTATUS_REF} from GitHub, only for testing"

# Version shown by the application (--version, /healthcheck, logs).
ENV MCSTATUS_HTTPD_VERSION=mcstatus-${MCSTATUS_REF}-test

COPY --from=build-venv /venv /venv
COPY --from=build-venv /app /app
COPY --from=build-venv --chown=nonroot:nonroot /cache/mcstatus-httpd /tmp/mcstatus-httpd

WORKDIR /app
STOPSIGNAL SIGINT
EXPOSE 8080

ENTRYPOINT ["/venv/bin/python3"]
CMD ["-u", "./mcstatus-httpd.py"]
