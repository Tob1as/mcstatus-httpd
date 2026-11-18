# mcstatus.io demo-server (https://github.com/mcstatus-io/demo-server)
# Fake Minecraft server (Java status + query, Bedrock status, Votifier) for testing.
#
# build: docker build --progress=plain --build-arg REF=main -t mcstatus-demo-server:latest .
#
# REF: branch, tag or commit SHA (GitHub archive URL accepts all of them).
ARG REF=main
ARG GO_VERSION=1.27

FROM alpine:latest AS source
ARG REF
# hadolint ignore=DL3018
RUN apk add --no-cache ca-certificates wget tar && \
    mkdir -p /src && \
    wget -qO- "https://github.com/mcstatus-io/demo-server/archive/${REF}.tar.gz" \
        | tar -xz -C /src --strip-components=1


FROM golang:${GO_VERSION}-alpine AS build
WORKDIR /src
COPY --from=source /src/go.mod /src/go.sum ./
RUN go mod download
COPY --from=source /src/ ./
# Fix: full stat query sends "game_type", vanilla (and Python mcstatus) expects "gametype".
# No-op once fixed upstream.
RUN sed -i 's/"game_type":/"gametype":/' src/query/packets.go && \
    CGO_ENABLED=0 go build -trimpath -ldflags="-s -w" -o /out/demo-server ./src


FROM scratch AS production
ARG REF
LABEL org.opencontainers.image.source="https://github.com/mcstatus-io/demo-server" \
      org.opencontainers.image.version="${REF}" \
      org.opencontainers.image.title="mcstatus-demo-server"

COPY --from=build /out/demo-server /app/demo-server
# Config is read from ./config.yml (relative to the working dir); mount your own over it.
COPY --from=source /src/config.example.yml /app/config.yml

WORKDIR /app
# nobody:nogroup (numeric, scratch has no /etc/passwd)
USER 65534:65534
# 25565/tcp Java status, 25565/udp Java query, 19132/udp Bedrock status, 8192/tcp Votifier
EXPOSE 25565/tcp 25565/udp 19132/udp 8192/tcp
STOPSIGNAL SIGTERM
ENTRYPOINT ["/app/demo-server"]
