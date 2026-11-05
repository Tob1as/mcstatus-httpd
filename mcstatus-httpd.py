#!/usr/bin/env python3
"""mcstatus-httpd - Minecraft server status as JSON over HTTP.

https://github.com/Tob1as/mcstatus-httpd

Queries a Minecraft Java Edition and/or Bedrock Edition server with mcstatus
(https://github.com/py-mine/mcstatus) and serves the result as JSON.
Bedrock servers using the NetherNet transport (default since Bedrock 1.26.50)
are queried directly via HTTP (GET /v1/join), because mcstatus (as of version
14.2.0) only supports the legacy RakNet transport for Bedrock, see
https://github.com/py-mine/mcstatus/issues/1220

Requirements:
    Python >= 3.13, mcstatus >= 14.2.0

Configuration:
    Every setting can be provided as an environment variable or as a command
    line argument. Command line arguments take precedence over environment
    variables. Run with ``--help`` for details.

    Environment variable                Argument               Default
    ----------------------------------  ---------------------  ------------------
    MINECRAFT_JAVA_SERVER               --java-server          (disabled)
    MINECRAFT_JAVA_SERVER_PORT          --java-port            25565
    MINECRAFT_JAVA_SERVER_PORT_QUERY    --java-query-port      same as java port
    MINECRAFT_JAVA_SERVER_OVERWRITE     --java-overwrite       same as java server
    MINECRAFT_BEDROCK_SERVER            --bedrock-server       (disabled)
    MINECRAFT_BEDROCK_SERVER_PORT       --bedrock-port         19132
    MINECRAFT_BEDROCK_SERVER_OVERWRITE  --bedrock-overwrite    same as bedrock server
    MINECRAFT_BEDROCK_TRANSPORT         --bedrock-transport    auto (nethernet + raknet)
    MINECRAFT_TIMEOUT                   --timeout              3 (seconds)
    CACHE_TTL                           --cache-ttl            10 (seconds, 0 = off)
    HTTP_HOST                           --http-host            0.0.0.0 ("::" = IPv4 + IPv6)
    HTTP_PORT                           --http-port            8080
    HTTP_PREFIX                         --http-prefix          (none)
    HTTP_CORS_ORIGIN                    --http-cors-origin     * (all origins)
    HTTP_TRUSTED_PROXIES                --http-trusted-proxies (none)
    HTTPD_SSL_ENABLE                    --ssl / --no-ssl       0
    SSL_CERTFILE                        --ssl-certfile         ssl.crt
    SSL_KEYFILE                         --ssl-keyfile          ssl.key
    AVATAR_ENABLE                       --avatar / --no-avatar 0
    AVATAR_TYPE                         --avatar-type          head (body, head3d, body3d)
    AVATAR_IMAGE_SIZE                   --avatar-image-size    64 (pixels, 8-300)
    AVATAR_ALLOWED_TYPES                --avatar-allowed-types head,body,head3d,body3d
    AVATAR_ALLOWED_SIZES                --avatar-allowed-sizes 16,32,48,64,96,128,192,256,300
    AVATAR_PROVIDERS                    --avatar-providers     mc-heads,minotar,crafthead
    AVATAR_CACHE_TTL                    --avatar-cache-ttl     3600 (seconds)
    AVATAR_CACHE_TYPE                   --avatar-cache-type    memory (or file)
    AVATAR_CACHE_DIR                    --avatar-cache-dir     /tmp/mcstatus-httpd/avatars
    AVATAR_CACHE_MAX_ENTRIES            --avatar-cache-max-entries 500 (0 = unlimited)
    AVATAR_TLS_VERIFY                   --[no-]avatar-tls-verify 1 (own URL templates only)
    AVATAR_ONLINE_ONLY                  --[no-]avatar-online-only 1 (0 = any valid name)
    AVATAR_TYPE_FALLBACK                --[no-]avatar-type-fallback 1 (head3d -> head, body3d -> body)
    PLAYER_UUID_LOOKUP                  --[no-]player-uuid-lookup 1 (0 = always the name)
    PLAYER_UUID_PROVIDERS               --player-uuid-providers mojang,minecraftservices,playerdb,minetools
    PLAYER_UUID_CACHE_TTL               --player-uuid-cache-ttl 86400 (seconds)
    PLAYER_UUID_CACHE_TYPE              --player-uuid-cache-type memory (or file)
    PLAYER_UUID_CACHE_FILE              --player-uuid-cache-file /tmp/mcstatus-httpd/uuids.json
    PLAYER_UUID_CACHE_MAX_ENTRIES       --player-uuid-cache-max-entries 1000 (0 = unlimited)
    LOGLEVEL                            --loglevel             INFO

    At least one server (Java or Bedrock) must be configured. A server that is
    not configured is omitted from the JSON output.

Endpoints (example with HTTP_PREFIX="mcstatus"):
    GET|HEAD /mcstatus               Minecraft server status (JSON)
    GET|HEAD /mcstatus/healthcheck   Health check of this service (JSON)
    GET|HEAD /healthcheck            Health check, always available without prefix
    GET|HEAD /mcstatus/avatar/<name> Avatar of a Java player who is online (PNG, only with AVATAR_ENABLE,
                                     any player name with AVATAR_ONLINE_ONLY=0),
                                     optional "?type=body&size=128" (AVATAR_ALLOWED_TYPES/_SIZES)
    Without a prefix the status is served at "/".

Container health check:
    python3 mcstatus-httpd.py --healthcheck
    Exits with 0 if the running service answers on /healthcheck, otherwise 1.
"""

import sys

# Fail early with a readable message instead of an ImportError further down.
if sys.version_info < (3, 13):
    sys.exit("mcstatus-httpd requires Python 3.13 or newer.")

import argparse
import contextlib
import http.client
import ipaddress
import json
import logging
import math
import os
import platform
import re
import signal
import socket
import ssl
import tempfile
import threading
import time
import urllib.error
import urllib.request
from collections import OrderedDict
from collections.abc import Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import UTC, datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.metadata import version as package_version
from pathlib import Path
from typing import Any, Final, cast, override
from urllib.parse import parse_qs, quote, unquote, urlsplit

from mcstatus import BedrockServer, JavaServer
from mcstatus.motd import Motd

# Used when no version is provided, e.g. when the script is run directly from the repository.
DEFAULT_VERSION: Final = "dev"


def _resolve_version() -> str:
    """Return the application version.

    Docker builds pass the build argument VERSION, which the Dockerfile exposes
    as environment variable MCSTATUS_HTTPD_VERSION (the GitHub workflow uses
    "<build date>.<commit hash>", e.g. "20261103054500.a1b2c3d4").
    Falls back to DEFAULT_VERSION if the variable is unset or invalid.
    """
    value = os.environ.get("MCSTATUS_HTTPD_VERSION", "").strip()
    # Only allow safe characters, the version is also sent in the "Server" HTTP header.
    return value if re.fullmatch(r"[0-9A-Za-z._+-]{1,64}", value) else DEFAULT_VERSION


__version__: Final = _resolve_version()

logger = logging.getLogger("mcstatus-httpd")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_JAVA_PORT: Final = 25565
DEFAULT_BEDROCK_PORT: Final = 19132

# Seconds a client may take to send its request (including the TLS handshake).
REQUEST_TIMEOUT: Final = 10.0
# Seconds the "--healthcheck" self-check waits for an answer.
HEALTHCHECK_TIMEOUT: Final = 5.0

# Generic error text for offline servers. Details are only written to the log,
# so internal hostnames/IPs are not exposed to public clients.
OFFLINE_ERROR_MESSAGE: Final = "Server unreachable"

# Servers/plugins use this UUID for fake entries in the player sample
# (e.g. advertising text instead of real player names).
NIL_UUID: Final = "00000000-0000-0000-0000-000000000000"

LOG_LEVELS: Final = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")
TRUE_VALUES: Final = frozenset({"1", "true", "yes", "on"})
FALSE_VALUES: Final = frozenset({"0", "false", "no", "off"})

# Link to the source code in the status JSON ("sourcecode"), see collect_status().
# Not documented: MCSTATUS_HTTPD_SOURCECODE=0 removes it from the output.
SOURCE_CODE_URL: Final = "https://github.com/Tob1as/mcstatus-httpd"
SHOW_SOURCE_CODE: Final = os.environ.get("MCSTATUS_HTTPD_SOURCECODE", "").strip().lower() not in FALSE_VALUES

type IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address
type IPNetwork = ipaddress.IPv4Network | ipaddress.IPv6Network

# Bedrock transports: "nethernet" (default since BDS 1.26.50, TCP + HTTP),
# "raknet" (legacy, UDP), "auto" = query both at the same time.
BEDROCK_TRANSPORTS: Final = ("auto", "nethernet", "raknet")
# NetherNet "gameType" values of GET /v1/join.
NETHERNET_GAME_TYPES: Final = {0: "Survival", 1: "Creative", 2: "Adventure"}
# Upper limit for the NetherNet status response (normally ~200 bytes).
NETHERNET_MAX_RESPONSE_SIZE: Final = 64 * 1024

# Player avatars. Built-in providers with URL templates per avatar type,
# "{id}" is replaced by the UUID of the player (or the name if unknown, see
# PLAYER_UUID_*), "{name}" by the player name and "{size}" by the image size.
# Verified: all providers deliver the same images for head and body (with helm/outer layer),
# crafthead with slightly different colors of single body pixels.
#   head, body: flat pixel art, head NxN, body Nx2N pixels (N = size)
#   head3d:     isometric head WITHOUT helm (minotar/crafthead have no helm variant), facing right,
#               the perspective differs a little between the providers
#   body3d:     isometric body, facing right, only mc-heads
AVATAR_TYPES: Final = ("head", "body", "head3d", "body3d")
AVATAR_BUILTIN_PROVIDERS: Final = {
    "mc-heads": {  # https://mc-heads.net/
        "head": "https://mc-heads.net/avatar/{id}/{size}.png",
        "body": "https://mc-heads.net/player/{id}/{size}.png",
        "head3d": "https://mc-heads.net/head/{id}/{size}/nohelm.png",
        "body3d": "https://mc-heads.net/body/{id}/{size}.png",
    },
    "minotar": {  # https://minotar.net/
        "head": "https://minotar.net/helm/{id}/{size}.png",
        "body": "https://minotar.net/armor/body/{id}/{size}.png",
        "head3d": "https://minotar.net/cube/{id}/{size}.png",
    },
    "crafthead": {  # https://crafthead.net/ (same URL layout as minotar)
        "head": "https://crafthead.net/helm/{id}/{size}.png",
        "body": "https://crafthead.net/armor/body/{id}/{size}.png",
        "head3d": "https://crafthead.net/cube/{id}/{size}.png",
    },
}
# Allowed image width in pixels requested from the providers (AVATAR_IMAGE_SIZE, AVATAR_ALLOWED_SIZES).
# All providers deliver at least 8 px, minotar and crafthead at most 300 px (mc-heads 600 px).
AVATAR_MIN_IMAGE_SIZE: Final = 8
AVATAR_MAX_IMAGE_SIZE: Final = 300
# Upper limit for an avatar image in bytes (a 300 px body is about 3 KB).
AVATAR_MAX_IMAGE_BYTES: Final = 64 * 1024
# Where avatars and player UUIDs are cached: in memory (lost on restart) or as file(s).
CACHE_TYPES: Final = ("memory", "file")
# Seconds to wait for an avatar provider.
AVATAR_FETCH_TIMEOUT: Final = 5.0
# Seconds a failing provider is skipped (rate limits use "Retry-After", up to the maximum).
AVATAR_PROVIDER_PAUSE: Final = 300.0
AVATAR_PROVIDER_MAX_PAUSE: Final = 3600.0
# Seconds a failed avatar lookup is remembered, so not every page view retries it.
AVATAR_FAILURE_TTL: Final = 300.0
# With AVATAR_TYPE_FALLBACK a 3D avatar that no provider delivers (and that is not cached)
# is replaced by the flat one, so a website does not show the name instead of an avatar.
AVATAR_TYPE_FALLBACKS: Final = {"head3d": "head", "body3d": "body"}
# Maximum number of remembered failed lookups (memory only, independent of the avatar cache).
AVATAR_FAILURE_MAX_ENTRIES: Final = 1000
# Valid Minecraft Java Edition player names.
PLAYER_NAME_PATTERN: Final = re.compile(r"[A-Za-z0-9_]{1,16}")
# Size query parameter of the avatar endpoint (the value must also be in AVATAR_ALLOWED_SIZES).
AVATAR_SIZE_PATTERN: Final = re.compile(r"[0-9]{1,3}")
# Own URL template with optional type prefix, e.g. "head=http://minecraft:8100/{name}.png".
AVATAR_TYPE_PREFIX_PATTERN: Final = re.compile(r"([a-z0-9]+)=(.*)", re.IGNORECASE)
PNG_SIGNATURE: Final = b"\x89PNG\r\n\x1a\n"

# Player UUIDs (name -> UUID), used for the "{id}" placeholder of the avatar providers.
# Built-in lookup services, "{name}" is replaced by the player name. Each one answers
# differently, see _parse_player_uuid().
PLAYER_UUID_BUILTIN_PROVIDERS: Final = {
    "mojang": "https://api.mojang.com/users/profiles/minecraft/{name}",
    "minecraftservices": "https://api.minecraftservices.com/minecraft/profile/lookup/name/{name}",
    "playerdb": "https://playerdb.co/api/player/minecraft/{name}",
    "minetools": "https://api.minetools.eu/uuid/{name}",
}
# Seconds to wait for a UUID lookup service.
PLAYER_UUID_FETCH_TIMEOUT: Final = 3.0
# Seconds a failing UUID lookup service is skipped (rate limits use "Retry-After").
PLAYER_UUID_PROVIDER_PAUSE: Final = 300.0
# Upper limit for an answer of a UUID lookup service (normally below 2 KB).
PLAYER_UUID_MAX_RESPONSE_SIZE: Final = 64 * 1024
# Seconds an unknown name is remembered at most (a new account may get this name).
PLAYER_UUID_UNKNOWN_TTL: Final = 3600.0
# A UUID without dashes.
PLAYER_UUID_PATTERN: Final = re.compile(r"[0-9a-f]{32}")


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class JavaTarget:
    """Connection settings of a Minecraft Java Edition server."""

    host: str
    port: int  # game port (TCP), used for the status fallback and shown in the output
    query_port: int  # query port (UDP)
    display_hostname: str  # hostname shown in the JSON output


@dataclass(frozen=True, slots=True)
class BedrockTarget:
    """Connection settings of a Minecraft Bedrock Edition server."""

    host: str
    port: int  # game port (NetherNet: TCP, RakNet: UDP)
    display_hostname: str  # hostname shown in the JSON output
    transport: str  # one of BEDROCK_TRANSPORTS


@dataclass(frozen=True, slots=True)
class AvatarProvider:
    """An avatar provider with its URL templates per avatar type."""

    label: str  # shown in the log, e.g. "mc-heads" or the host of an own URL template
    templates: Mapping[str, str]  # avatar type -> URL with "{id}"/"{name}" and optional "{size}"
    verify_tls: bool = True  # False = accept any HTTPS certificate (only own URL templates)


@dataclass(frozen=True, slots=True)
class Settings:
    """Complete, validated application settings."""

    java: JavaTarget | None  # None = not configured, omitted from output
    bedrock: BedrockTarget | None  # None = not configured, omitted from output
    timeout: float
    cache_ttl: float
    http_host: str
    http_port: int
    http_prefix: str  # normalized: "" or "/segment[/segment...]"
    cors_origins: tuple[str, ...]  # ("*",) = all origins, otherwise allowed origins
    trusted_proxies: tuple[IPNetwork, ...]  # empty = X-Forwarded-For is ignored
    ssl_enabled: bool
    ssl_certfile: Path
    ssl_keyfile: Path
    avatar_enabled: bool
    avatar_type: str  # default type, one of AVATAR_TYPES
    avatar_image_size: int  # default width in pixels requested from the providers ({size})
    avatar_allowed_types: tuple[str, ...]  # types allowed via ?type=, includes the default
    avatar_allowed_sizes: tuple[int, ...]  # sizes allowed via ?size=, includes the default
    avatar_providers: tuple[AvatarProvider, ...]  # in order of preference (fallback order)
    avatar_cache_ttl: float
    avatar_cache_type: str  # one of CACHE_TYPES
    avatar_cache_dir: Path  # only used with avatar_cache_type "file"
    avatar_cache_max_entries: int  # 0 = unlimited
    avatar_tls_verify: bool  # False = no certificate check for own URL templates
    avatar_online_only: bool  # True = only avatars of players in the current status
    avatar_type_fallback: bool  # True = flat avatar if a 3D avatar is not available
    player_uuid_lookup: bool  # False = "{id}" is always the player name
    player_uuid_providers: tuple[str, ...]  # names of PLAYER_UUID_BUILTIN_PROVIDERS, fallback order
    player_uuid_cache_ttl: float
    player_uuid_cache_type: str  # one of CACHE_TYPES
    player_uuid_cache_file: Path  # only used with player_uuid_cache_type "file"
    player_uuid_cache_max_entries: int  # 0 = unlimited
    loglevel: str


def _env(name: str, default: str | None = None) -> str | None:
    """Return the stripped value of an environment variable.

    Empty values are treated like unset variables, so ``FOO=`` in a compose
    file falls back to the default.
    """
    value = os.environ.get(name, "").strip()
    return value or default


def _port(value: str) -> int:
    """Argument type: TCP/UDP port number (1-65535)."""
    try:
        port = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"invalid port {value!r}") from None
    if not 1 <= port <= 65535:
        raise argparse.ArgumentTypeError(f"port {port} is out of range 1-65535")
    return port


def _finite_float(value: str) -> float:
    """Parse a finite float or raise an argparse error."""
    try:
        number = float(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"invalid number {value!r}") from None
    if not math.isfinite(number):
        raise argparse.ArgumentTypeError(f"invalid number {value!r}")
    return number


def _timeout(value: str) -> float:
    """Argument type: timeout in seconds (> 0)."""
    seconds = _finite_float(value)
    if seconds <= 0:
        raise argparse.ArgumentTypeError("timeout must be greater than 0")
    return seconds


def _cache_ttl(value: str) -> float:
    """Argument type: cache lifetime in seconds (>= 0, 0 disables caching)."""
    seconds = _finite_float(value)
    if seconds < 0:
        raise argparse.ArgumentTypeError("cache TTL must not be negative")
    return seconds


def _loglevel(value: str) -> str:
    """Argument type: logging level name (case-insensitive)."""
    level = value.strip().upper()
    if level not in LOG_LEVELS:
        raise argparse.ArgumentTypeError(
            f"invalid log level {value!r}, choose from {', '.join(LOG_LEVELS)}"
        )
    return level


def _prefix(value: str) -> str:
    """Argument type: URL path prefix.

    "mcstatus", "/mcstatus", "/mcstatus/" -> "/mcstatus"
    "mc/status"                           -> "/mc/status"
    "", "/"                               -> "" (no prefix)
    """
    segments = [segment for segment in value.strip().split("/") if segment]
    return "/" + "/".join(segments) if segments else ""


def _cors_origins(value: str) -> tuple[str, ...]:
    """Argument type: allowed CORS origins.

    "*"                                              -> ("*",) = all origins
    "https://forum.example.com, https://example.com" -> only these origins
    """
    origins: list[str] = []
    for item in value.split(","):
        origin = item.strip().rstrip("/").lower()
        if not origin:
            continue
        if origin == "*":
            return ("*",)
        parts = urlsplit(origin)
        if parts.scheme not in ("http", "https") or not parts.netloc or parts.path or parts.query:
            raise argparse.ArgumentTypeError(
                f"invalid origin {item.strip()!r}, expected e.g. 'https://forum.example.com'"
            )
        origins.append(origin)
    return tuple(origins) or ("*",)


def _trusted_proxies(value: str) -> tuple[IPNetwork, ...]:
    """Argument type: trusted reverse proxies as IP addresses and/or networks.

    "172.18.0.0/16, 10.0.0.5" -> (IPv4Network('172.18.0.0/16'), IPv4Network('10.0.0.5/32'))
    ""                        -> () = disabled
    """
    networks: list[IPNetwork] = []
    for item in value.split(","):
        if not (item := item.strip()):
            continue
        try:
            networks.append(ipaddress.ip_network(item, strict=False))
        except ValueError:
            raise argparse.ArgumentTypeError(
                f"invalid IP address or network {item!r}, expected e.g. '172.18.0.0/16' or '10.0.0.5'"
            ) from None
    return tuple(networks)


def _parse_ip(value: str) -> IPAddress | None:
    """Parse an IP address, return None if invalid.

    IPv4-mapped IPv6 addresses ("::ffff:172.18.0.2", used when listening on "::")
    are converted to plain IPv4 addresses.
    """
    try:
        ip = ipaddress.ip_address(value.strip())
    except ValueError:
        return None
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        return ip.ipv4_mapped
    return ip


def _is_trusted(ip: IPAddress, networks: tuple[IPNetwork, ...]) -> bool:
    """Check if an IP address belongs to one of the trusted networks."""
    return any(ip in network for network in networks)


def _bedrock_transport(value: str) -> str:
    """Argument type: Bedrock transport (case-insensitive), one of BEDROCK_TRANSPORTS."""
    transport = value.strip().lower()
    if transport not in BEDROCK_TRANSPORTS:
        raise argparse.ArgumentTypeError(
            f"invalid transport {value!r}, choose from {', '.join(BEDROCK_TRANSPORTS)}"
        )
    return transport


def _avatar_type(value: str) -> str:
    """Argument type: avatar type (case-insensitive), one of AVATAR_TYPES."""
    avatar_type = value.strip().lower()
    if avatar_type not in AVATAR_TYPES:
        raise argparse.ArgumentTypeError(
            f"invalid avatar type {value!r}, choose from {', '.join(AVATAR_TYPES)}"
        )
    return avatar_type


def _avatar_image_size(value: str) -> int:
    """Argument type: avatar image width in pixels (AVATAR_MIN_IMAGE_SIZE-AVATAR_MAX_IMAGE_SIZE)."""
    try:
        size = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"invalid image size {value!r}") from None
    if not AVATAR_MIN_IMAGE_SIZE <= size <= AVATAR_MAX_IMAGE_SIZE:
        raise argparse.ArgumentTypeError(
            f"image size {size} is out of range {AVATAR_MIN_IMAGE_SIZE}-{AVATAR_MAX_IMAGE_SIZE}"
        )
    return size


def _avatar_types(value: str) -> tuple[str, ...]:
    """Argument type: comma separated list of avatar types."""
    types = tuple(dict.fromkeys(_avatar_type(item) for item in value.split(",") if item.strip()))
    if not types:
        raise argparse.ArgumentTypeError("at least one avatar type is required")
    return types


def _avatar_image_sizes(value: str) -> tuple[int, ...]:
    """Argument type: comma separated list of avatar image sizes, sorted."""
    sizes = tuple(sorted({_avatar_image_size(item.strip()) for item in value.split(",") if item.strip()}))
    if not sizes:
        raise argparse.ArgumentTypeError("at least one avatar image size is required")
    return sizes


def _cache_type(value: str) -> str:
    """Argument type: cache type (case-insensitive), one of CACHE_TYPES."""
    cache_type = value.strip().lower()
    if cache_type not in CACHE_TYPES:
        raise argparse.ArgumentTypeError(
            f"invalid cache type {value!r}, choose from {', '.join(CACHE_TYPES)}"
        )
    return cache_type


def _cache_max_entries(value: str) -> int:
    """Argument type: maximum number of cache entries (>= 0, 0 = unlimited)."""
    try:
        entries = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"invalid number {value!r}") from None
    if entries < 0:
        raise argparse.ArgumentTypeError("the number of cache entries must not be negative")
    return entries


def _avatar_providers(value: str) -> tuple[tuple[str | None, str], ...]:
    """Argument type: avatar providers in order of preference.

    Each entry is a built-in provider (see AVATAR_BUILTIN_PROVIDERS) or an own
    URL template with "{name}" (or "{id}" = UUID) and optional "{size}", e.g. of
    a server plugin. An own URL template can start with "<type>=" if it only
    delivers this type:
    "head=http://minecraft:8100/tiles/faces/32x32/{name}.png, mc-heads, minotar"

    Returns:
        (type or None, provider) pairs. Type None = built-in provider or own
        URL template for the default avatar type.
    """
    providers: list[tuple[str | None, str]] = []
    for item in value.split(","):
        if not (item := item.strip()):
            continue
        if item.lower() in AVATAR_BUILTIN_PROVIDERS:
            providers.append((None, item.lower()))
            continue
        avatar_type: str | None = None
        if (match := AVATAR_TYPE_PREFIX_PATTERN.fullmatch(item)) and match.group(1).lower() in AVATAR_TYPES:
            avatar_type, item = match.group(1).lower(), match.group(2).strip()
            if item.lower() in AVATAR_BUILTIN_PROVIDERS:
                raise argparse.ArgumentTypeError(
                    f"a type prefix is only possible for own URL templates, not for {item!r}"
                )
        parts = urlsplit(item)
        if (parts.scheme not in ("http", "https") or not parts.netloc
                or ("{name}" not in item and "{id}" not in item)):
            raise argparse.ArgumentTypeError(
                f"invalid avatar provider {item!r}, use {', '.join(AVATAR_BUILTIN_PROVIDERS)} "
                "or an URL template like '[head=]https://example.com/avatar/{name}/{size}.png'"
            )
        providers.append((avatar_type, item))
    if not providers:
        raise argparse.ArgumentTypeError("at least one avatar provider is required")
    return tuple(providers)


def _player_uuid_providers(value: str) -> tuple[str, ...]:
    """Argument type: UUID lookup services in order of preference, see PLAYER_UUID_BUILTIN_PROVIDERS."""
    providers: list[str] = []
    for item in value.split(","):
        if not (item := item.strip().lower()):
            continue
        if item not in PLAYER_UUID_BUILTIN_PROVIDERS:
            raise argparse.ArgumentTypeError(
                f"invalid UUID provider {item!r}, choose from {', '.join(PLAYER_UUID_BUILTIN_PROVIDERS)}"
            )
        if item not in providers:
            providers.append(item)
    if not providers:
        raise argparse.ArgumentTypeError("at least one UUID provider is required")
    return tuple(providers)


def _parse_bool(value: str) -> bool:
    """Parse a boolean flag like "1", "true", "yes", "on" (case-insensitive)."""
    normalized = value.strip().lower()
    if normalized in TRUE_VALUES:
        return True
    if normalized in FALSE_VALUES:
        return False
    raise ValueError(f"invalid boolean value {value!r}, use 1/0, true/false, yes/no or on/off")


def build_arg_parser() -> argparse.ArgumentParser:
    """Create the command line parser.

    Defaults are taken from environment variables. argparse also runs the
    ``type`` converter on string defaults, so values from the environment are
    validated exactly like command line values.
    """
    parser = argparse.ArgumentParser(
        prog="mcstatus-httpd",
        description="Serve the status of a Minecraft Java and/or Bedrock server as JSON over HTTP.",
        epilog=(
            "Every option can also be set via the environment variable shown in brackets. "
            "Command line arguments take precedence over environment variables."
        ),
    )

    def option(
        group: argparse._ArgumentGroup,
        *flags: str,
        env: str,
        text: str,
        default: str | None = None,
        **kwargs: Any,
    ) -> None:
        """Add an option whose default is read from an environment variable."""
        group.add_argument(*flags, default=_env(env, default), help=f"{text} [env: {env}]", **kwargs)

    java = parser.add_argument_group("Minecraft Java Edition")
    option(java, "--java-server", env="MINECRAFT_JAVA_SERVER", metavar="HOST",
           text="Java server address. Not set = Java is disabled.")
    option(java, "--java-port", env="MINECRAFT_JAVA_SERVER_PORT", default=str(DEFAULT_JAVA_PORT),
           type=_port, metavar="PORT", text=f"Java game port, TCP (default: {DEFAULT_JAVA_PORT}).")
    option(java, "--java-query-port", env="MINECRAFT_JAVA_SERVER_PORT_QUERY", type=_port, metavar="PORT",
           text="Java query port, UDP (default: same as --java-port).")
    option(java, "--java-overwrite", env="MINECRAFT_JAVA_SERVER_OVERWRITE", metavar="HOST",
           text="Hostname shown in the output (default: same as --java-server).")

    bedrock = parser.add_argument_group("Minecraft Bedrock Edition")
    option(bedrock, "--bedrock-server", env="MINECRAFT_BEDROCK_SERVER", metavar="HOST",
           text="Bedrock server address. Not set = Bedrock is disabled.")
    option(bedrock, "--bedrock-port", env="MINECRAFT_BEDROCK_SERVER_PORT", default=str(DEFAULT_BEDROCK_PORT),
           type=_port, metavar="PORT",
           text=f"Bedrock game port, NetherNet: TCP, RakNet: UDP (default: {DEFAULT_BEDROCK_PORT}).")
    option(bedrock, "--bedrock-overwrite", env="MINECRAFT_BEDROCK_SERVER_OVERWRITE", metavar="HOST",
           text="Hostname shown in the output (default: same as --bedrock-server).")
    option(bedrock, "--bedrock-transport", env="MINECRAFT_BEDROCK_TRANSPORT", default="auto",
           type=_bedrock_transport, metavar="TRANSPORT",
           text="Bedrock protocol: 'nethernet' (TCP, default since Bedrock 1.26.50), 'raknet' (UDP, legacy) "
                "or 'auto' = try both at the same time (default: auto).")

    query = parser.add_argument_group("Query behaviour")
    option(query, "--timeout", env="MINECRAFT_TIMEOUT", default="3", type=_timeout, metavar="SECONDS",
           text="Seconds to wait for a Minecraft server before it counts as offline (default: 3).")
    option(query, "--cache-ttl", env="CACHE_TTL", default="10", type=_cache_ttl, metavar="SECONDS",
           text="Seconds a status result is reused before the servers are queried again, "
                "0 = query on every request (default: 10).")

    http = parser.add_argument_group("HTTP server")
    option(http, "--http-host", env="HTTP_HOST", default="0.0.0.0", metavar="HOST",
           text="Address to listen on, use '::' for IPv4 + IPv6 (default: 0.0.0.0 = IPv4 only).")
    option(http, "--http-port", env="HTTP_PORT", default="8080", type=_port, metavar="PORT",
           text="Port to listen on (default: 8080).")
    option(http, "--http-prefix", env="HTTP_PREFIX", default="", type=_prefix, metavar="PATH",
           text="Sub path for all endpoints, e.g. 'mcstatus' -> /mcstatus (default: none).")
    option(http, "--http-cors-origin", env="HTTP_CORS_ORIGIN", default="*", type=_cors_origins, metavar="ORIGINS",
           text="Websites allowed to load the status (CORS), '*' or a comma separated list "
                "like 'https://forum.example.com,https://example.com' (default: * = all).")
    option(http, "--http-trusted-proxies", env="HTTP_TRUSTED_PROXIES", default="", type=_trusted_proxies,
           metavar="NETWORKS",
           text="Reverse proxies (IPs/networks, comma separated, e.g. '172.18.0.0/16') whose "
                "X-Forwarded-For/X-Real-IP header is used for the client IP in the log (default: none).")
    http.add_argument("--ssl", action=argparse.BooleanOptionalAction, default=None,
                      help="Enable HTTPS (default: disabled). [env: HTTPD_SSL_ENABLE]")
    option(http, "--ssl-certfile", env="SSL_CERTFILE", default="ssl.crt", type=Path, metavar="FILE",
           text="TLS certificate file (default: ssl.crt).")
    option(http, "--ssl-keyfile", env="SSL_KEYFILE", default="ssl.key", type=Path, metavar="FILE",
           text="TLS private key file (default: ssl.key).")

    avatar = parser.add_argument_group("Player avatars (Java)")
    avatar.add_argument("--avatar", action=argparse.BooleanOptionalAction, default=None,
                        help="Serve player avatars at <prefix>/avatar/<name>, loaded from the "
                             "providers and cached (default: disabled). [env: AVATAR_ENABLE]")
    option(avatar, "--avatar-type", env="AVATAR_TYPE", default="head", type=_avatar_type, metavar="TYPE",
           text=f"Default avatar type: {', '.join(AVATAR_TYPES)} (default: head).")
    option(avatar, "--avatar-image-size", env="AVATAR_IMAGE_SIZE", default="64", type=_avatar_image_size,
           metavar="PIXELS",
           text=f"Default image width requested from the providers ({{size}}), {AVATAR_MIN_IMAGE_SIZE}-"
                f"{AVATAR_MAX_IMAGE_SIZE}, body images are twice as high (default: 64).")
    option(avatar, "--avatar-allowed-types", env="AVATAR_ALLOWED_TYPES", default=",".join(AVATAR_TYPES),
           type=_avatar_types, metavar="TYPES",
           text="Avatar types that can be requested with ?type=, comma separated, the default type is "
                f"always allowed (default: {','.join(AVATAR_TYPES)}).")
    option(avatar, "--avatar-allowed-sizes", env="AVATAR_ALLOWED_SIZES", default="16,32,48,64,96,128,192,256,300",
           type=_avatar_image_sizes, metavar="SIZES",
           text="Image widths that can be requested with ?size=, comma separated, the default size is "
                "always allowed (default: 16,32,48,64,96,128,192,256,300).")
    option(avatar, "--avatar-providers", env="AVATAR_PROVIDERS", default=",".join(AVATAR_BUILTIN_PROVIDERS),
           type=_avatar_providers, metavar="PROVIDERS",
           text="Avatar providers in order of preference, the next one is used if a provider fails: "
                f"{', '.join(AVATAR_BUILTIN_PROVIDERS)} or own URL templates with {{name}} (or {{id}} = UUID) "
                "and {size}, optionally limited to one type with '<type>=' "
                f"(default: {','.join(AVATAR_BUILTIN_PROVIDERS)}).")
    option(avatar, "--avatar-cache-ttl", env="AVATAR_CACHE_TTL", default="3600", type=_cache_ttl,
           metavar="SECONDS",
           text="Seconds an avatar is used before it is loaded again, if loading fails the old avatar "
                "is kept (default: 3600).")
    option(avatar, "--avatar-cache-type", env="AVATAR_CACHE_TYPE", default="memory", type=_cache_type,
           metavar="TYPE",
           text="Where avatars are cached: 'memory' (lost on restart) or 'file' (directory, "
                "see --avatar-cache-dir) (default: memory).")
    option(avatar, "--avatar-cache-dir", env="AVATAR_CACHE_DIR", default="/tmp/mcstatus-httpd/avatars",
           type=Path, metavar="DIR",
           text="Directory of the file cache, created if missing (default: /tmp/mcstatus-httpd/avatars).")
    option(avatar, "--avatar-cache-max-entries", env="AVATAR_CACHE_MAX_ENTRIES", default="500",
           type=_cache_max_entries, metavar="NUMBER",
           text="Maximum number of cached avatars (every type and size counts), the least recently "
                "used ones are removed first, 0 = unlimited (default: 500).")
    avatar.add_argument("--avatar-tls-verify", action=argparse.BooleanOptionalAction, default=None,
                        help="Verify the HTTPS certificates of own avatar URL templates, disable for "
                             "self-signed certificates (default: enabled, built-in providers are always "
                             "verified). [env: AVATAR_TLS_VERIFY]")
    avatar.add_argument("--avatar-online-only", action=argparse.BooleanOptionalAction, default=None,
                        help="Only serve avatars of players who are currently online, disable to allow any "
                             "valid player name (default: enabled). [env: AVATAR_ONLINE_ONLY]")
    avatar.add_argument("--avatar-type-fallback", action=argparse.BooleanOptionalAction, default=None,
                        help="Serve the flat avatar if a 3D avatar is not available (head3d -> head, "
                             "body3d -> body), with a short browser cache time (default: enabled). "
                             "[env: AVATAR_TYPE_FALLBACK]")

    uuid = parser.add_argument_group("Player UUIDs (used for {id} of the avatar providers)")
    uuid.add_argument("--player-uuid-lookup", action=argparse.BooleanOptionalAction, default=None,
                      help="Look up the UUID of a player by name, disable to always use the name "
                           "(default: enabled). [env: PLAYER_UUID_LOOKUP]")
    option(uuid, "--player-uuid-providers", env="PLAYER_UUID_PROVIDERS",
           default=",".join(PLAYER_UUID_BUILTIN_PROVIDERS), type=_player_uuid_providers, metavar="PROVIDERS",
           text="UUID lookup services in order of preference, the next one is used if a service fails "
                f"(default: {','.join(PLAYER_UUID_BUILTIN_PROVIDERS)}).")
    option(uuid, "--player-uuid-cache-ttl", env="PLAYER_UUID_CACHE_TTL", default="86400", type=_cache_ttl,
           metavar="SECONDS",
           text="Seconds a UUID is used before it is looked up again, if that fails the old UUID is kept "
                f"(unknown names at most {PLAYER_UUID_UNKNOWN_TTL:g}) (default: 86400).")
    option(uuid, "--player-uuid-cache-type", env="PLAYER_UUID_CACHE_TYPE", default="memory", type=_cache_type,
           metavar="TYPE",
           text="Where UUIDs are cached: 'memory' (lost on restart) or 'file' (JSON file, "
                "see --player-uuid-cache-file) (default: memory).")
    option(uuid, "--player-uuid-cache-file", env="PLAYER_UUID_CACHE_FILE", default="/tmp/mcstatus-httpd/uuids.json",
           type=Path, metavar="FILE",
           text="JSON file of the UUID cache, created if missing (default: /tmp/mcstatus-httpd/uuids.json).")
    option(uuid, "--player-uuid-cache-max-entries", env="PLAYER_UUID_CACHE_MAX_ENTRIES", default="1000",
           type=_cache_max_entries, metavar="NUMBER",
           text="Maximum number of cached UUIDs, the least recently used ones are removed first, "
                "0 = unlimited (default: 1000).")

    misc = parser.add_argument_group("Miscellaneous")
    option(misc, "--loglevel", env="LOGLEVEL", default="INFO", type=_loglevel, metavar="LEVEL",
           text=f"Log level: {', '.join(LOG_LEVELS)} (default: INFO).")
    misc.add_argument("--healthcheck", action="store_true",
                      help="Check if the running service is healthy and exit with 0 (healthy) or 1.")
    misc.add_argument("--version", action="version", version=f"%(prog)s {__version__}")

    return parser


def parse_settings(argv: Sequence[str] | None = None) -> tuple[Settings, bool]:
    """Parse command line arguments and environment variables.

    Args:
        argv: Arguments without the program name, ``None`` = ``sys.argv[1:]``.

    Returns:
        The validated settings and whether ``--healthcheck`` was requested.
    """
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    def env_bool(value: bool | None, env: str, default: str = "0") -> bool:
        """Value of a --flag/--no-flag option, otherwise of its environment variable."""
        # BooleanOptionalAction cannot convert string defaults, so the
        # environment variable is evaluated here.
        if value is not None:
            return value
        try:
            return _parse_bool(_env(env, default) or default)
        except ValueError as exc:
            parser.error(f"{env}: {exc}")

    ssl_enabled = env_bool(args.ssl, "HTTPD_SSL_ENABLE")
    avatar_enabled = env_bool(args.avatar, "AVATAR_ENABLE")
    avatar_tls_verify = env_bool(args.avatar_tls_verify, "AVATAR_TLS_VERIFY", default="1")
    avatar_online_only = env_bool(args.avatar_online_only, "AVATAR_ONLINE_ONLY", default="1")
    avatar_type_fallback = env_bool(args.avatar_type_fallback, "AVATAR_TYPE_FALLBACK", default="1")
    player_uuid_lookup = env_bool(args.player_uuid_lookup, "PLAYER_UUID_LOOKUP", default="1")

    # Built-in providers deliver every type, own URL templates the type of their prefix
    # or the default type. Disabling the certificate check only affects own URL templates.
    avatar_providers = tuple(
        AvatarProvider(provider, AVATAR_BUILTIN_PROVIDERS[provider])
        if provider in AVATAR_BUILTIN_PROVIDERS
        else AvatarProvider(urlsplit(provider).netloc, {avatar_type or args.avatar_type: provider},
                            verify_tls=avatar_tls_verify)
        for avatar_type, provider in args.avatar_providers
    )
    # The defaults can always be requested, even if they are missing in the allowed lists.
    avatar_allowed_types = tuple(dict.fromkeys((args.avatar_type, *args.avatar_allowed_types)))
    avatar_allowed_sizes = tuple(sorted({args.avatar_image_size, *args.avatar_allowed_sizes}))

    java: JavaTarget | None = None
    if java_host := (args.java_server or "").strip():
        java = JavaTarget(
            host=java_host,
            port=args.java_port,
            query_port=args.java_query_port or args.java_port,
            display_hostname=args.java_overwrite or java_host,
        )

    bedrock: BedrockTarget | None = None
    if bedrock_host := (args.bedrock_server or "").strip():
        bedrock = BedrockTarget(
            host=bedrock_host,
            port=args.bedrock_port,
            display_hostname=args.bedrock_overwrite or bedrock_host,
            transport=args.bedrock_transport,
        )

    # The health check only talks to the local HTTP server, no MC server needed.
    if java is None and bedrock is None and not args.healthcheck:
        parser.error(
            "no Minecraft server configured, set MINECRAFT_JAVA_SERVER and/or "
            "MINECRAFT_BEDROCK_SERVER (or --java-server / --bedrock-server)"
        )

    settings = Settings(
        java=java,
        bedrock=bedrock,
        timeout=args.timeout,
        cache_ttl=args.cache_ttl,
        http_host=args.http_host,
        http_port=args.http_port,
        http_prefix=args.http_prefix,
        cors_origins=args.http_cors_origin,
        trusted_proxies=args.http_trusted_proxies,
        ssl_enabled=ssl_enabled,
        ssl_certfile=args.ssl_certfile,
        ssl_keyfile=args.ssl_keyfile,
        avatar_enabled=avatar_enabled,
        avatar_type=args.avatar_type,
        avatar_image_size=args.avatar_image_size,
        avatar_allowed_types=avatar_allowed_types,
        avatar_allowed_sizes=avatar_allowed_sizes,
        avatar_providers=avatar_providers,
        avatar_cache_ttl=args.avatar_cache_ttl,
        avatar_cache_type=args.avatar_cache_type,
        avatar_cache_dir=args.avatar_cache_dir,
        avatar_cache_max_entries=args.avatar_cache_max_entries,
        avatar_tls_verify=avatar_tls_verify,
        avatar_online_only=avatar_online_only,
        avatar_type_fallback=avatar_type_fallback,
        player_uuid_lookup=player_uuid_lookup,
        player_uuid_providers=args.player_uuid_providers,
        player_uuid_cache_ttl=args.player_uuid_cache_ttl,
        player_uuid_cache_type=args.player_uuid_cache_type,
        player_uuid_cache_file=args.player_uuid_cache_file,
        player_uuid_cache_max_entries=args.player_uuid_cache_max_entries,
        loglevel=args.loglevel,
    )
    return settings, args.healthcheck


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def setup_logging(level: str) -> None:
    """Configure logging to stdout (container friendly)."""
    logging.basicConfig(
        format="%(asctime)s %(name)-14s %(levelname)-8s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stdout,
        level=level,
        force=True,  # replace handlers that may have been installed before
    )


def utc_now() -> str:
    """Return the current time in ISO 8601 format, e.g. "2026-01-01T12:00:00+00:00"."""
    return datetime.now(UTC).isoformat(timespec="seconds")


def format_host(host: str) -> str:
    """Wrap IPv6 addresses in brackets for use in URLs."""
    return f"[{host}]" if ":" in host else host


# ---------------------------------------------------------------------------
# Minecraft queries
# ---------------------------------------------------------------------------


def _offline(hostname: str, port: int) -> dict[str, Any]:
    """Build the output for a server that could not be reached."""
    return {"hostname": hostname, "port": port, "online": False, "error": OFFLINE_ERROR_MESSAGE}


def query_java(target: JavaTarget, timeout: float) -> dict[str, Any]:
    """Query a Java Edition server.

    1. Query protocol (UDP): full player list, plugins and map name.
       Requires ``enable-query=true`` in the server.properties.
    2. Fallback status protocol (TCP, the "server list ping"): works on every
       server, but only provides a player *sample* (up to ~12 names, may be
       hidden or modified by the server) and no plugins or map name.

    Never raises, an unreachable server is returned as offline.
    """
    server = JavaServer(target.host, target.port, timeout=timeout, query_port=target.query_port)

    # mcstatus raises various exceptions (OSError, TimeoutError, ValueError, ...)
    # depending on what went wrong, so all of them are handled the same way.
    try:
        query = server.query(tries=1)
    except Exception as exc:
        logger.debug("Java query on %s:%d failed (%r), falling back to status",
                     target.host, target.query_port, exc)
    else:
        logger.info("Java server: %d/%d players online, list: %s",
                    query.players.online, query.players.max, ", ".join(query.players.list) or "none")
        return {
            "hostname": target.display_hostname,
            "port": target.port,
            "online": True,
            "software": {
                "version": query.software.version,
                "brand": query.software.brand,
                "plugins": list(query.software.plugins),
            },
            "players": {
                "online": query.players.online,
                "max": query.players.max,
                "list": list(query.players.list),
            },
            "map": query.map_name,
            "motd": query.motd.to_plain(),
        }

    try:
        status = server.status(tries=1)
    except Exception as exc:
        logger.warning("Java server %s:%d is unreachable: %r", target.host, target.port, exc)
        return _offline(target.display_hostname, target.port)

    # Skip fake sample entries (NIL UUID), they are not real players.
    players = [player.name for player in status.players.sample or [] if player.id != NIL_UUID]
    logger.info("Java server (status fallback): %d/%d players online, sample: %s",
                status.players.online, status.players.max, ", ".join(players) or "none")
    return {
        "hostname": target.display_hostname,
        "port": target.port,
        "online": True,
        "software": {
            "version": status.version.name,
            "brand": None,  # not provided by the status protocol
            "plugins": [],  # not provided by the status protocol
        },
        "players": {
            "online": status.players.online,
            "max": status.players.max,
            "list": players,
        },
        "map": None,  # not provided by the status protocol
        "motd": status.motd.to_plain(),
    }


def query_bedrock(target: BedrockTarget, timeout: float) -> dict[str, Any]:
    """Query a Bedrock Edition server via NetherNet and/or RakNet.

    With transport "auto" both protocols are queried at the same time and the
    first successful answer is used, so neither protocol has to wait for the
    timeout of the other one.

    Never raises, an unreachable server is returned as offline.
    """
    transports = ("nethernet", "raknet") if target.transport == "auto" else (target.transport,)
    queries = {"nethernet": _query_bedrock_nethernet, "raknet": _query_bedrock_raknet}
    errors: list[str] = []

    pool = ThreadPoolExecutor(max_workers=len(transports), thread_name_prefix="bedrock-query")
    try:
        futures = {pool.submit(queries[transport], target, timeout): transport for transport in transports}
        # as_completed() yields the queries in the order they finish: the first
        # successful one is returned, failed ones are collected for the log.
        for future in as_completed(futures):
            transport = futures[future]
            try:
                return future.result()
            except Exception as exc:  # see query_java() for why all exceptions are caught
                logger.debug("Bedrock %s query on %s:%d failed (%r)", transport, target.host, target.port, exc)
                errors.append(f"{transport}: {exc!r}")
    finally:
        # Do not wait for the slower query, it ends on its own after the timeout.
        pool.shutdown(wait=False, cancel_futures=True)

    logger.warning("Bedrock server %s:%d is unreachable: %s", target.host, target.port, "; ".join(errors))
    return _offline(target.display_hostname, target.port)


def _bedrock_result(target: BedrockTarget, **values: Any) -> dict[str, Any]:
    """Build the JSON output of an online Bedrock server (same for both transports)."""
    return {
        "hostname": target.display_hostname,
        "port": target.port,
        "online": True,
        "software": {
            "version": values["version"],
            "brand": values["brand"],
            "protocol": values["protocol"],
        },
        "players": {
            "online": values["players_online"],
            "max": values["players_max"],
        },
        "map": values["map"],
        "motd": values["motd"],
        "gamemode": values["gamemode"],
    }


def _query_bedrock_nethernet(target: BedrockTarget, timeout: float) -> dict[str, Any]:
    """Query a Bedrock server via NetherNet (BDS >= 1.26.50, default transport).

    The server answers "GET /v1/join" on its TCP game port with JSON, e.g.
    {"name": "Dedicated Server", "protocol": 2235, "version": "1.26.70",
     "level": "Bedrock level", "players": 0, "maxPlayers": 10, "gameType": 0}
    See https://mojang.github.io/bedrock-protocol-docs/guides/nether-net-onboarding-guide/

    Raises:
        OSError: Connection failed or the server does not support NetherNet (non-2xx).
        ValueError: Invalid response.
    """
    # Plain HTTP (no TLS), a new connection for every query.
    connection = http.client.HTTPConnection(target.host, target.port, timeout=timeout)
    try:
        connection.request("GET", "/v1/join", headers={
            "Accept": "application/json",
            "User-Agent": f"mcstatus-httpd/{__version__}",
        })
        response = connection.getresponse()
        body = response.read(NETHERNET_MAX_RESPONSE_SIZE + 1)
    finally:
        connection.close()

    if not 200 <= response.status < 300:
        raise OSError(f"NetherNet not supported (HTTP {response.status})")
    if len(body) > NETHERNET_MAX_RESPONSE_SIZE:
        raise ValueError("NetherNet response too large")
    data = json.loads(body)
    if not isinstance(data, dict):
        raise ValueError("unexpected NetherNet response")

    players_online = int(data.get("players", 0))
    players_max = int(data.get("maxPlayers", 0))
    game_type = data.get("gameType")
    logger.info("Bedrock server (NetherNet): %d/%d players online", players_online, players_max)
    return _bedrock_result(
        target,
        version=data.get("version"),
        brand=None,  # not provided by NetherNet
        protocol=data.get("protocol"),
        players_online=players_online,
        players_max=players_max,
        map=data.get("level"),
        # The server name can contain formatting codes like the RakNet MOTD.
        motd=Motd.parse(str(data.get("name", "")), bedrock=True).to_plain(),
        gamemode=NETHERNET_GAME_TYPES.get(game_type, None if game_type is None else str(game_type)),
    )


def _query_bedrock_raknet(target: BedrockTarget, timeout: float) -> dict[str, Any]:
    """Query a Bedrock server via RakNet (UDP, legacy transport) using mcstatus."""
    status = BedrockServer(target.host, target.port, timeout=timeout).status(tries=1)
    logger.info("Bedrock server (RakNet): %d/%d players online", status.players.online, status.players.max)
    return _bedrock_result(
        target,
        version=status.version.name,
        brand=status.version.brand,
        protocol=status.version.protocol,
        players_online=status.players.online,
        players_max=status.players.max,
        map=status.map_name,
        motd=status.motd.to_plain(),
        gamemode=status.gamemode,
    )


def collect_status(settings: Settings) -> dict[str, Any]:
    """Query all configured servers in parallel and build the JSON payload.

    Servers that are not configured are omitted from the result.
    """
    result: dict[str, Any] = {"date": utc_now()}

    with ThreadPoolExecutor(max_workers=2, thread_name_prefix="mc-query") as pool:
        futures = {}
        if settings.java is not None:
            futures["java"] = pool.submit(query_java, settings.java, settings.timeout)
        if settings.bedrock is not None:
            futures["bedrock"] = pool.submit(query_bedrock, settings.bedrock, settings.timeout)

    # Leaving the "with" block waits for all queries, insertion order keeps "java" first.
    for key, future in futures.items():
        result[key] = future.result()

    # Tells the websites that avatars are available, the defaults and what can be requested.
    #if settings.avatar_enabled:
    #    result["avatar"] = {
    #        "type": settings.avatar_type,
    #        "size": settings.avatar_image_size,
    #        "types": list(settings.avatar_allowed_types),
    #        "sizes": list(settings.avatar_allowed_sizes),
    #        "path": f"{settings.http_prefix}/avatar/",
    #    }

    # Link to the source code, comment out these two lines to remove it.
    if SHOW_SOURCE_CODE:
        result["sourcecode"] = SOURCE_CODE_URL
    return result


class StatusCache:
    """Thread-safe cache for the status payload.

    The lock is held while the servers are queried, so concurrent requests
    wait for the running query instead of starting their own. This limits the
    load on the Minecraft servers to one query round per TTL.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._lock = threading.Lock()
        self._payload: dict[str, Any] | None = None
        self._expires_at = 0.0

    def get(self) -> dict[str, Any]:
        """Return the cached payload, refreshing it if it has expired."""
        with self._lock:
            if self._payload is None or time.monotonic() >= self._expires_at:
                self._payload = collect_status(self._settings)
                # Measured after the query, so a slow query does not shorten the cache lifetime.
                self._expires_at = time.monotonic() + self._settings.cache_ttl
            return self._payload


# ---------------------------------------------------------------------------
# Player UUIDs
# ---------------------------------------------------------------------------


class PlayerUUIDProviderError(Exception):
    """A UUID lookup service failed (not reachable, rate limit, unexpected answer).

    ``pause`` is the number of seconds the service should be skipped.
    """

    def __init__(self, message: str, pause: float) -> None:
        super().__init__(message)
        self.pause = pause


def _parse_player_uuid(provider: str, status: int, data: Any) -> str | None:
    """Extract the UUID from the answer of a lookup service.

    Returns:
        The UUID without dashes, None if the service does not know the name.

    Raises:
        ValueError: Unexpected answer.
    """
    if not isinstance(data, dict):
        data = {}
    if provider in ("mojang", "minecraftservices"):
        # {"id": "853c80ef...", "name": "jeb_"}, unknown name: HTTP 404 (formerly 204 without body)
        if status in (HTTPStatus.NOT_FOUND, HTTPStatus.NO_CONTENT):
            return None
        value = data.get("id") if status == HTTPStatus.OK else None
    elif provider == "playerdb":
        # {"code": "player.found", "data": {"player": {"raw_id": "853c80ef...", ...}}},
        # unknown name: HTTP 400 {"code": "minecraft.invalid_username", ...}
        if data.get("code") == "minecraft.invalid_username":
            return None
        player = (data.get("data") or {}).get("player") or {} if status == HTTPStatus.OK else {}
        value = player.get("raw_id") or player.get("id") if isinstance(player, dict) else None
    else:  # minetools
        # {"id": "853c80ef...", "name": "jeb_", "status": "OK"}, unknown name: HTTP 200
        # {"id": null, "name": "...", "status": "ERR"} or {"error": "Invalid UUID or nickname.", "status": "ERR"}
        if data.get("status") == "ERR" and (
            ("id" in data and data["id"] is None) or "invalid" in str(data.get("error", "")).lower()
        ):
            return None
        value = data.get("id") if data.get("status") == "OK" else None
    uuid = str(value or "").replace("-", "").lower()
    if not PLAYER_UUID_PATTERN.fullmatch(uuid):
        raise ValueError(f"unexpected answer (HTTP {status})")
    return uuid


def _fetch_player_uuid(provider: str, name: str) -> str | None:
    """Ask a lookup service for the UUID of a player.

    Returns:
        The UUID without dashes, None if the service does not know the name.

    Raises:
        PlayerUUIDProviderError: The service failed, the next one should be asked.
    """
    url = PLAYER_UUID_BUILTIN_PROVIDERS[provider].replace("{name}", quote(name))
    request = urllib.request.Request(url, headers={
        "Accept": "application/json",
        "User-Agent": f"mcstatus-httpd/{__version__}",
    })
    try:
        with urllib.request.urlopen(request, timeout=PLAYER_UUID_FETCH_TIMEOUT) as response:
            status, body = response.status, response.read(PLAYER_UUID_MAX_RESPONSE_SIZE + 1)
    except urllib.error.HTTPError as exc:
        if exc.code == HTTPStatus.TOO_MANY_REQUESTS:
            raise PlayerUUIDProviderError("HTTP 429 (rate limit)",
                                          pause=_retry_after(exc.headers.get("Retry-After"))) from None
        if exc.code >= 500:
            raise PlayerUUIDProviderError(f"HTTP {exc.code}", pause=PLAYER_UUID_PROVIDER_PAUSE) from None
        # Some services answer an unknown name with 400/404 and a JSON body.
        status = exc.code
        try:
            body = exc.read(PLAYER_UUID_MAX_RESPONSE_SIZE + 1)
        except (OSError, http.client.HTTPException):
            body = b""
    except (OSError, ValueError, http.client.HTTPException) as exc:  # URLError, timeout, broken answer
        raise PlayerUUIDProviderError(repr(exc), pause=PLAYER_UUID_PROVIDER_PAUSE) from None

    try:
        if len(body) > PLAYER_UUID_MAX_RESPONSE_SIZE:
            raise ValueError("answer too large")
        return _parse_player_uuid(provider, status, json.loads(body) if body.strip() else None)
    except (ValueError, AttributeError, TypeError) as exc:
        raise PlayerUUIDProviderError(f"invalid answer: {exc}", pause=PLAYER_UUID_PROVIDER_PAUSE) from None


class PlayerUUIDCache:
    """Cache player name (lower case) -> (time of the lookup, UUID or None = unknown name).

    In memory, or additionally as JSON file that is read on start and written on
    every change. The file stores the time of the lookup (not the expiry), so a
    changed TTL also applies to existing entries:
    {"jeb_": {"id": "853c80ef3c3749fdaa49938b674adae6", "time": 1793413600}, ...}
    """

    def __init__(self, max_entries: int, file: Path | None) -> None:
        self._max_entries = max_entries  # 0 = unlimited
        self._file = file  # None = memory only
        self._lock = threading.Lock()
        self._entries: OrderedDict[str, tuple[float, str | None]] = OrderedDict()  # least recently used first
        if file is not None:
            file.parent.mkdir(parents=True, exist_ok=True)
            if not os.access(file.parent, os.W_OK | os.X_OK) or (file.exists() and not os.access(file, os.W_OK)):
                raise PermissionError(f"player UUID cache file is not writable: {file}")
            self._load(file)
            logger.info("Player UUID cache: %d entries in %s", len(self._entries), file)

    def _load(self, file: Path) -> None:
        """Read the cache file, invalid entries are skipped."""
        try:
            data = json.loads(file.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return
        except (OSError, ValueError) as exc:
            logger.warning("Ignoring invalid player UUID cache file %s: %s", file, exc)
            return
        if not isinstance(data, dict):
            logger.warning("Ignoring invalid player UUID cache file %s", file)
            return
        for name, entry in data.items():  # stored in least recently used order
            if not (PLAYER_NAME_PATTERN.fullmatch(name) and name == name.lower() and isinstance(entry, dict)):
                continue
            uuid, stored_at = entry.get("id"), entry.get("time")
            if uuid is not None and not (isinstance(uuid, str) and PLAYER_UUID_PATTERN.fullmatch(uuid)):
                continue
            if not (isinstance(stored_at, (int, float)) and math.isfinite(stored_at)):
                continue
            self._entries[name] = (float(stored_at), uuid)
        self._evict()

    def get(self, name: str) -> tuple[float, str | None] | None:
        """Return (time of the lookup, UUID or None = unknown name), None if not cached."""
        with self._lock:
            entry = self._entries.get(name)
            if entry is not None:
                self._entries.move_to_end(name)
            return entry

    def put(self, name: str, uuid: str | None) -> None:
        """Cache the result of a lookup, removes the least recently used entries above the limit."""
        with self._lock:
            self._entries[name] = (time.time(), uuid)
            self._entries.move_to_end(name)
            self._evict()
            if self._file is not None:
                self._save(self._file)

    def _evict(self) -> None:
        while self._max_entries and len(self._entries) > self._max_entries:
            self._entries.popitem(last=False)

    def _save(self, file: Path) -> None:
        """Write the cache file (the caller holds the lock)."""
        data = {name: {"id": uuid, "time": round(stored_at)} for name, (stored_at, uuid) in self._entries.items()}
        try:
            # Write to a temporary file first, so the file is never partly written.
            fd, temp_name = tempfile.mkstemp(dir=file.parent, prefix=".", suffix=".tmp")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    json.dump(data, handle, separators=(",", ":"))
                os.replace(temp_name, file)
            except BaseException:
                with contextlib.suppress(OSError):
                    os.unlink(temp_name)
                raise
        except OSError as exc:
            logger.warning("Cannot write player UUID cache file %s: %s", file, exc)


class PlayerUUIDs:
    """Looks up the UUIDs of players by name (not only usable for avatars).

    The services are asked in the configured order. A service that fails is
    skipped for a while, so the next one is used. If a service does not know the
    name, no other service is asked. A cached UUID older than the TTL is looked up
    again, if that fails the old UUID is used (the UUID of an account never changes,
    only a name can move to another account).
    """

    def __init__(self, settings: Settings) -> None:
        self._providers = settings.player_uuid_providers
        self._ttl = settings.player_uuid_cache_ttl
        self._cache = PlayerUUIDCache(
            settings.player_uuid_cache_max_entries,
            settings.player_uuid_cache_file if settings.player_uuid_cache_type == "file" else None,
        )
        self._lock = threading.Lock()  # one lookup at a time, protects the provider pauses
        self._paused_until: dict[str, float] = {}  # provider -> time.monotonic()

    def lookup(self, name: str) -> str | None:
        """Return the UUID (without dashes) of a player, None if unknown or no service answered."""
        if not PLAYER_NAME_PATTERN.fullmatch(name):
            return None
        key = name.lower()
        entry = self._cache.get(key)
        if entry is not None and self._is_fresh(entry):
            return entry[1]
        with self._lock:
            # Another request may have looked up the name while this one was waiting.
            entry = self._cache.get(key)
            if entry is not None and self._is_fresh(entry):
                return entry[1]
            answered, uuid = self._query(name)
            if answered:
                self._cache.put(key, uuid)
                return uuid
        if entry is not None:
            logger.debug("UUID of %s could not be updated, using the cached one", name)
            return entry[1]
        return None

    def uuid_or_name(self, name: str) -> str:
        """Return the UUID of a player, the name if it is unknown or no service answered."""
        return self.lookup(name) or name

    def _is_fresh(self, entry: tuple[float, str | None]) -> bool:
        stored_at, uuid = entry
        ttl = self._ttl if uuid is not None else min(self._ttl, PLAYER_UUID_UNKNOWN_TTL)
        return time.time() - stored_at < ttl

    def _query(self, name: str) -> tuple[bool, str | None]:
        """Ask the services in order (the caller holds the lock).

        Returns:
            (answered, UUID or None = unknown name), answered is False if no service answered.
        """
        for provider in self._providers:
            if self._paused_until.get(provider, 0.0) > time.monotonic():
                continue
            try:
                uuid = _fetch_player_uuid(provider, name)
            except PlayerUUIDProviderError as exc:
                self._paused_until[provider] = time.monotonic() + exc.pause
                logger.warning("UUID provider %s failed for %s (%s), paused for %gs", provider, name, exc, exc.pause)
                continue
            if uuid is None:
                logger.debug("UUID provider %s does not know %s", provider, name)
            else:
                logger.debug("UUID of %s loaded from %s: %s", name, provider, uuid)
            return True, uuid
        logger.debug("No UUID provider answered for %s, using the name", name)
        return False, None


def _uses_player_id(settings: Settings) -> bool:
    """Whether an avatar provider uses the "{id}" placeholder, only then UUIDs are looked up."""
    return any("{id}" in template for provider in settings.avatar_providers for template in provider.templates.values())


# ---------------------------------------------------------------------------
# Player avatars
# ---------------------------------------------------------------------------


class AvatarProviderError(Exception):
    """An avatar provider did not deliver an avatar.

    ``pause`` is the number of seconds the provider should be skipped,
    0 = the provider works, but has no avatar for this player.
    """

    def __init__(self, message: str, pause: float) -> None:
        super().__init__(message)
        self.pause = pause


def _retry_after(value: str | None) -> float:
    """Pause in seconds from a "Retry-After" header, limited to AVATAR_PROVIDER_MAX_PAUSE."""
    try:
        seconds = float(value) if value else AVATAR_PROVIDER_PAUSE
    except ValueError:  # the HTTP date format is not supported, use the default
        seconds = AVATAR_PROVIDER_PAUSE
    if not math.isfinite(seconds):
        seconds = AVATAR_PROVIDER_PAUSE
    return min(max(seconds, 1.0), AVATAR_PROVIDER_MAX_PAUSE)


def _download_avatar(url: str, context: ssl.SSLContext | None = None) -> bytes:
    """Download an avatar and check that it is a PNG image.

    Args:
        url: Avatar URL (http or https).
        context: TLS context for HTTPS, None = default context with certificate check.

    Raises:
        AvatarProviderError: Download failed or the answer is not a valid PNG.
    """
    request = urllib.request.Request(url, headers={
        "Accept": "image/png",
        "User-Agent": f"mcstatus-httpd/{__version__}",
    })
    try:
        with urllib.request.urlopen(request, timeout=AVATAR_FETCH_TIMEOUT, context=context) as response:
            image = response.read(AVATAR_MAX_IMAGE_BYTES + 1)
    except urllib.error.HTTPError as exc:
        if exc.code == HTTPStatus.NOT_FOUND:
            # Unknown player, the provider itself works: try the next one without pausing it.
            raise AvatarProviderError("HTTP 404", pause=0) from None
        if exc.code == HTTPStatus.TOO_MANY_REQUESTS:
            raise AvatarProviderError("HTTP 429 (rate limit)", pause=_retry_after(exc.headers.get("Retry-After"))) from None
        raise AvatarProviderError(f"HTTP {exc.code}", pause=AVATAR_PROVIDER_PAUSE) from None
    except (OSError, ValueError, http.client.HTTPException) as exc:  # URLError, timeout, broken answer
        raise AvatarProviderError(repr(exc), pause=AVATAR_PROVIDER_PAUSE) from None

    if len(image) > AVATAR_MAX_IMAGE_BYTES or not image.startswith(PNG_SIGNATURE):
        raise AvatarProviderError("invalid image", pause=AVATAR_PROVIDER_PAUSE)
    return image


# (player name in lower case, avatar type, image size). Mojang player names are case-insensitive.
type AvatarKey = tuple[str, str, int]


class MemoryAvatarCache:
    """Avatar cache in memory, lost on restart."""

    def __init__(self, max_entries: int) -> None:
        self._max_entries = max_entries  # 0 = unlimited
        self._lock = threading.Lock()
        # key -> (time.time() when stored, PNG), least recently used first
        self._entries: OrderedDict[AvatarKey, tuple[float, bytes]] = OrderedDict()

    def load(self, key: AvatarKey) -> tuple[float, bytes] | None:
        """Return (time stored, PNG) of a cached avatar, None if not cached."""
        with self._lock:
            entry = self._entries.get(key)
            if entry is not None:
                self._entries.move_to_end(key)
            return entry

    def store(self, key: AvatarKey, image: bytes) -> None:
        """Cache an avatar, removes the least recently used ones above the limit."""
        with self._lock:
            self._entries[key] = (time.time(), image)
            self._entries.move_to_end(key)
            while self._max_entries and len(self._entries) > self._max_entries:
                self._entries.popitem(last=False)


class FileAvatarCache:
    """Avatar cache as PNG files "<dir>/<type>/<size>/<name>.png", kept across restarts.

    The time an avatar was stored is the modification time of its file. Only
    files of this naming scheme are read or deleted, other files are ignored.
    The index (least recently used order) is kept in memory and rebuilt on start.
    """

    def __init__(self, directory: Path, max_entries: int) -> None:
        self._directory = directory
        self._max_entries = max_entries  # 0 = unlimited
        self._lock = threading.Lock()  # protects the index
        self._index: OrderedDict[AvatarKey, None] = OrderedDict()  # least recently used first
        directory.mkdir(parents=True, exist_ok=True)
        if not os.access(directory, os.W_OK | os.X_OK):
            raise PermissionError(f"avatar cache directory is not writable: {directory}")
        self._load_index()
        logger.info("Avatar cache: %d files in %s", len(self._index), directory)
        self._evict()

    def _path(self, key: AvatarKey) -> Path:
        name, avatar_type, size = key
        return self._directory / avatar_type / str(size) / f"{name}.png"

    def _load_index(self) -> None:
        """Index the existing avatar files, the oldest ones first."""
        found: list[tuple[float, AvatarKey]] = []
        for avatar_type in AVATAR_TYPES:
            type_dir = self._directory / avatar_type
            if not type_dir.is_dir():
                continue
            for size_dir in type_dir.iterdir():
                if not (size_dir.is_dir() and AVATAR_SIZE_PATTERN.fullmatch(size_dir.name)
                        and str(int(size_dir.name)) == size_dir.name):
                    continue
                for path in size_dir.iterdir():
                    if path.name.startswith(".") and path.name.endswith(".tmp"):
                        # Left over from an interrupted write.
                        with contextlib.suppress(OSError):
                            path.unlink()
                        continue
                    name = path.name.removesuffix(".png")
                    if (path.name.endswith(".png") and PLAYER_NAME_PATTERN.fullmatch(name)
                            and name == name.lower() and path.is_file()):
                        found.append((path.stat().st_mtime, (name, avatar_type, int(size_dir.name))))
        for _, key in sorted(found):
            self._index[key] = None

    def load(self, key: AvatarKey) -> tuple[float, bytes] | None:
        """Return (time stored, PNG) of a cached avatar, None if not cached."""
        path = self._path(key)
        try:
            stored_at = path.stat().st_mtime
            image = path.read_bytes()
        except FileNotFoundError:
            image = None
        except OSError as exc:
            logger.warning("Cannot read avatar cache file %s: %s", path, exc)
            image = None
        if image is not None and (len(image) > AVATAR_MAX_IMAGE_BYTES or not image.startswith(PNG_SIGNATURE)):
            logger.warning("Ignoring invalid avatar cache file %s", path)
            image = None
        with self._lock:
            if image is None:
                self._index.pop(key, None)
                return None
            self._index[key] = None
            self._index.move_to_end(key)
        return stored_at, image

    def store(self, key: AvatarKey, image: bytes) -> None:
        """Cache an avatar, removes the least recently used ones above the limit."""
        path = self._path(key)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            # Write to a temporary file first, so readers never get a partly written avatar.
            fd, temp_name = tempfile.mkstemp(dir=path.parent, prefix=".", suffix=".tmp")
            try:
                with os.fdopen(fd, "wb") as file:
                    file.write(image)
                os.replace(temp_name, path)
            except BaseException:
                with contextlib.suppress(OSError):
                    os.unlink(temp_name)
                raise
        except OSError as exc:
            logger.warning("Cannot write avatar cache file %s: %s", path, exc)
            return
        with self._lock:
            self._index[key] = None
            self._index.move_to_end(key)
        self._evict()

    def _evict(self) -> None:
        """Delete the least recently used avatars above the limit."""
        while self._max_entries:
            with self._lock:
                if len(self._index) <= self._max_entries:
                    return
                key, _ = self._index.popitem(last=False)
            try:
                self._path(key).unlink(missing_ok=True)
            except OSError as exc:
                logger.warning("Cannot delete avatar cache file %s: %s", self._path(key), exc)


class AvatarStore:
    """Loads player avatars from the configured providers and caches them.

    The providers are tried in the configured order. A provider that fails
    (timeout, server error, rate limit, invalid image) is skipped for a while,
    so the next provider is used and the failing one is not stressed further.
    An avatar older than the TTL is loaded again on the next request. If no
    provider delivers it, the old avatar is kept and used.
    Visitors only talk to mcstatus-httpd, the providers never see their IP addresses.
    """

    def __init__(self, settings: Settings, uuids: PlayerUUIDs | None = None) -> None:
        self._providers = settings.avatar_providers
        self._uuids = uuids  # None = "{id}" is the player name
        self._type_fallback = settings.avatar_type_fallback
        self._ttl = settings.avatar_cache_ttl
        self._cache: MemoryAvatarCache | FileAvatarCache = (
            FileAvatarCache(settings.avatar_cache_dir, settings.avatar_cache_max_entries)
            if settings.avatar_cache_type == "file"
            else MemoryAvatarCache(settings.avatar_cache_max_entries)
        )
        self._lock = threading.Lock()  # protects the failures and the provider pauses
        self._download_lock = threading.Lock()  # one download at a time, avatars change rarely
        # key -> time.monotonic() until a failed lookup is not retried, oldest first
        self._failures: OrderedDict[AvatarKey, float] = OrderedDict()
        self._paused_until: dict[str, float] = {}  # provider label -> time.monotonic()
        # For own URL templates with AVATAR_TLS_VERIFY=0, e.g. a plugin with a self-signed certificate.
        self._insecure_context = ssl.create_default_context()
        self._insecure_context.check_hostname = False
        self._insecure_context.verify_mode = ssl.CERT_NONE

    def get_or_fallback(self, name: str, avatar_type: str, size: int) -> tuple[bytes, bool, str] | None:
        """Return the avatar of a player, with AVATAR_TYPE_FALLBACK the flat one if a 3D avatar is not available.

        The flat avatar is cached under its own type only, so the 3D avatar is
        loaded again on the next request after AVATAR_FAILURE_TTL.

        Returns:
            (PNG, fresh, delivered type) or None if no avatar is available.
            fresh is False for an outdated avatar and for a replacement.
        """
        if (result := self.get(name, avatar_type, size)) is not None:
            return result[0], result[1], avatar_type
        fallback = AVATAR_TYPE_FALLBACKS.get(avatar_type) if self._type_fallback else None
        if fallback is None or (result := self.get(name, fallback, size)) is None:
            return None
        logger.debug("Avatar %s (%s, %d px) not available, using %s instead", name, avatar_type, size, fallback)
        return result[0], False, fallback

    def get(self, name: str, avatar_type: str, size: int) -> tuple[bytes, bool] | None:
        """Return the avatar of a player.

        Returns:
            (PNG, fresh) or None if no provider has an avatar and none is cached.
            fresh is False if the cached avatar is older than the TTL, because
            it could not be loaded again.
        """
        key = (name.lower(), avatar_type, size)
        entry, usable = self._from_cache(key)
        if not usable:
            with self._download_lock:
                # Another request may have loaded the avatar while this one was waiting.
                entry, usable = self._from_cache(key)
                if not usable:
                    if (image := self._download(name, avatar_type, size)) is not None:
                        self._cache.store(key, image)
                        with self._lock:
                            self._failures.pop(key, None)
                        return image, True
                    self._remember_failure(key)
                    if entry is not None:
                        logger.debug("Avatar %s (%s, %d px) could not be updated, using the cached one",
                                     name, avatar_type, size)
        if entry is None:
            return None
        return entry[1], self._is_fresh(entry[0])

    def _is_fresh(self, stored_at: float) -> bool:
        return time.time() - stored_at < self._ttl

    def _from_cache(self, key: AvatarKey) -> tuple[tuple[float, bytes] | None, bool]:
        """Return the cache entry and whether it can be used without loading the avatar again.

        A cached avatar older than the TTL or a missing one is only loaded again
        if the last attempt for it did not fail recently.
        """
        entry = self._cache.load(key)
        if entry is not None and self._is_fresh(entry[0]):
            return entry, True
        with self._lock:
            retry_at = self._failures.get(key)
            if retry_at is not None and retry_at <= time.monotonic():
                del self._failures[key]
                retry_at = None
        return entry, retry_at is not None

    def _remember_failure(self, key: AvatarKey) -> None:
        """Do not try to load the avatar again for AVATAR_FAILURE_TTL seconds."""
        with self._lock:
            self._failures[key] = time.monotonic() + AVATAR_FAILURE_TTL
            self._failures.move_to_end(key)
            while len(self._failures) > AVATAR_FAILURE_MAX_ENTRIES:
                self._failures.popitem(last=False)

    def _download(self, name: str, avatar_type: str, size: int) -> bytes | None:
        """Try the providers of the avatar type in order until one delivers the avatar."""
        player_id: str | None = None  # UUID or name for "{id}", only looked up if needed
        for provider in self._providers:
            if (template := provider.templates.get(avatar_type)) is None:
                continue
            with self._lock:
                if self._paused_until.get(provider.label, 0.0) > time.monotonic():
                    continue
            if "{id}" in template and player_id is None:
                player_id = self._uuids.uuid_or_name(name) if self._uuids is not None else name
            url = (template.replace("{id}", quote(player_id or name)).replace("{name}", quote(name))
                   .replace("{size}", str(size)))
            try:
                image = _download_avatar(url, None if provider.verify_tls else self._insecure_context)
            except AvatarProviderError as exc:
                if exc.pause > 0:
                    with self._lock:
                        self._paused_until[provider.label] = time.monotonic() + exc.pause
                    logger.warning("Avatar provider %s failed for %s (%s), paused for %gs",
                                   provider.label, name, exc, exc.pause)
                else:
                    logger.debug("Avatar provider %s has no avatar for %s (%s)", provider.label, name, exc)
                continue
            logger.debug("Avatar of %s (%s, %d px) loaded from %s", name, avatar_type, size, provider.label)
            return image
        logger.debug("No avatar available for %s (%s, %d px)", name, avatar_type, size)
        return None


# ---------------------------------------------------------------------------
# HTTP server
# ---------------------------------------------------------------------------


def create_tls_context(certfile: Path, keyfile: Path) -> ssl.SSLContext:
    """Create a server-side TLS context.

    Raises:
        FileNotFoundError: If the certificate or key file does not exist.
        ssl.SSLError: If the files cannot be loaded.
    """
    for path in (certfile, keyfile):
        if not path.is_file():
            raise FileNotFoundError(f"TLS file not found: {path}")

    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    # Only affects TLS 1.2, the TLS 1.3 cipher suites are secure by default.
    context.set_ciphers("ECDHE+AESGCM:ECDHE+CHACHA20:DHE+AESGCM:DHE+CHACHA20")
    context.load_cert_chain(certfile=certfile, keyfile=keyfile)
    return context


class StatusHTTPServer(ThreadingHTTPServer):
    """Threaded HTTP(S) server holding settings and status cache."""

    # Request threads do not block the shutdown of the server.
    daemon_threads = True

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.cache = StatusCache(settings)
        # Player UUIDs are currently only needed for the "{id}" placeholder of the avatar providers.
        self.player_uuids = (
            PlayerUUIDs(settings)
            if settings.avatar_enabled and settings.player_uuid_lookup and _uses_player_id(settings)
            else None
        )
        self.avatars = AvatarStore(settings, self.player_uuids) if settings.avatar_enabled else None
        self.tls_context = (
            create_tls_context(settings.ssl_certfile, settings.ssl_keyfile)
            if settings.ssl_enabled
            else None
        )
        if ":" in settings.http_host:
            # Must be set before the base class creates the socket.
            self.address_family = socket.AF_INET6
        super().__init__((settings.http_host, settings.http_port), RequestHandler)

    @override
    def server_bind(self) -> None:
        # "::" accepts IPv4 and IPv6 (dual stack), independent of the OS default
        # (net.ipv6.bindv6only). IPv4 clients then appear as "::ffff:a.b.c.d".
        if self.address_family == socket.AF_INET6 and self.settings.http_host == "::":
            self.socket.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
        super().server_bind()

    @override
    def finish_request(self, request: socket.socket, client_address: Any) -> None:
        if self.tls_context is None:
            super().finish_request(request, client_address)
            return
        # The TLS handshake runs here, in the per-connection worker thread, so a
        # slow or malicious client cannot block the accept loop of the server.
        request.settimeout(REQUEST_TIMEOUT)
        with self.tls_context.wrap_socket(request, server_side=True) as tls_request:
            super().finish_request(tls_request, client_address)

    @override
    def handle_error(self, request: Any, client_address: Any) -> None:
        # The default implementation prints a traceback to stderr, e.g. for
        # every failed TLS handshake of a port scanner.
        logger.debug("Error while handling request from %s", client_address, exc_info=True)


class RequestHandler(BaseHTTPRequestHandler):
    """Routes requests to the status and health check endpoints."""

    server_version = f"mcstatus-httpd/{__version__}"
    sys_version = ""  # do not disclose the Python version in the "Server" header
    timeout = REQUEST_TIMEOUT  # protects against clients that never finish their request

    @property
    def app(self) -> StatusHTTPServer:
        """The server instance with typed access to settings and cache."""
        return cast(StatusHTTPServer, self.server)

    def do_GET(self) -> None:
        """Handle GET requests (headers and JSON body)."""
        self._dispatch(include_body=True)

    def do_HEAD(self) -> None:
        """Handle HEAD requests (headers only), e.g. used by monitoring tools."""
        self._dispatch(include_body=False)

    def _dispatch(self, *, include_body: bool) -> None:
        """Route a request by its path.

        The query string is ignored (e.g. "/?_=123" cache busters) and a
        trailing slash is accepted ("/mcstatus/" == "/mcstatus").
        Only the avatar endpoint evaluates the query string (type and size).
        """
        url = urlsplit(self.path)
        path = url.path.rstrip("/") or "/"
        prefix = self.app.settings.http_prefix
        avatar_prefix = f"{prefix}/avatar/"

        if path == (prefix or "/"):
            self._send_json(HTTPStatus.OK, self.app.cache.get(), include_body=include_body)
        elif path in (f"{prefix}/healthcheck", "/healthcheck"):
            health = {"status": "ok", "timestamp": utc_now(), "version": __version__}
            self._send_json(HTTPStatus.OK, health, include_body=include_body)
        elif self.app.avatars is not None and path.startswith(avatar_prefix):
            self._send_avatar(self.app.avatars, unquote(path.removeprefix(avatar_prefix)), url.query,
                              include_body=include_body)
        else:
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "Not found"}, include_body=include_body)

    def _send_avatar(self, avatars: AvatarStore, name: str, query: str, *, include_body: bool) -> None:
        """Send the avatar (PNG) of a Java player (by default only if currently online)."""
        settings = self.app.settings
        try:
            avatar_type, size = self._avatar_params(query)
        except ValueError as exc:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)}, include_body=include_body)
            return
        name = name.removesuffix(".png")
        # By default only players of the current status are allowed. Otherwise anybody could
        # use mcstatus-httpd to fetch arbitrary names from the avatar providers.
        allowed = PLAYER_NAME_PATTERN.fullmatch(name) and (
            not settings.avatar_online_only or name in self._online_players()
        )
        result = avatars.get_or_fallback(name, avatar_type, size) if allowed else None
        if result is None:
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "Not found"}, include_body=include_body)
            return
        image, fresh, delivered_type = result
        # Browsers may cache the avatar as long as mcstatus-httpd does. An outdated avatar
        # (could not be loaded again) or a replacement (flat instead of 3D) only until the
        # next attempt of mcstatus-httpd.
        max_age = settings.avatar_cache_ttl if fresh else min(settings.avatar_cache_ttl, AVATAR_FAILURE_TTL)
        cache_control = f"public, max-age={int(max_age)}"
        self._send_body(HTTPStatus.OK, "image/png", image, include_body=include_body, cache_control=cache_control,
                        extra_headers={"X-Avatar-Type": delivered_type})

    def _avatar_params(self, query: str) -> tuple[str, int]:
        """Avatar type and size from the query string ("?type=body&size=128"), defaults if missing.

        Raises:
            ValueError: Invalid or not allowed value, the message is sent to the client.
        """
        settings = self.app.settings
        try:
            params = parse_qs(query, keep_blank_values=True, max_num_fields=10)
        except ValueError:
            raise ValueError("invalid query string") from None

        avatar_type = settings.avatar_type
        if (types := params.get("type")) is not None:
            if len(types) != 1 or types[0].lower() not in settings.avatar_allowed_types:
                raise ValueError(f"invalid type, allowed: {', '.join(settings.avatar_allowed_types)}")
            avatar_type = types[0].lower()

        size = settings.avatar_image_size
        if (sizes := params.get("size")) is not None:
            if (len(sizes) != 1 or not AVATAR_SIZE_PATTERN.fullmatch(sizes[0])
                    or int(sizes[0]) not in settings.avatar_allowed_sizes):
                raise ValueError(f"invalid size, allowed: {', '.join(map(str, settings.avatar_allowed_sizes))}")
            size = int(sizes[0])
        return avatar_type, size

    def _online_players(self) -> set[str]:
        """Names of the Java players in the current (cached) status."""
        java = self.app.cache.get().get("java") or {}
        return set(java.get("players", {}).get("list", [])) if java.get("online") else set()

    def _send_json(self, status: HTTPStatus, payload: dict[str, Any], *, include_body: bool) -> None:
        """Send a JSON response (headers only for HEAD requests)."""
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self._send_body(status, "application/json; charset=utf-8", body, include_body=include_body)

    def _send_body(
        self,
        status: HTTPStatus,
        content_type: str,
        body: bytes,
        *,
        include_body: bool,
        cache_control: str = "no-store",
        extra_headers: Mapping[str, str] | None = None,
    ) -> None:
        """Send a response with CORS and security headers (headers only for HEAD requests)."""
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", cache_control)
        for header, value in (extra_headers or {}).items():
            self.send_header(header, value)
        allowed = self.app.settings.cors_origins
        if allowed == ("*",):
            self.send_header("Access-Control-Allow-Origin", "*")
        else:
            # Only answer with the requesting origin if it is allowed. Without the
            # header the browser blocks the response for other websites.
            origin = self.headers.get("Origin", "").strip().lower()
            if origin in allowed:
                self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        if include_body:
            self.wfile.write(body)

    @override
    def address_string(self) -> str:
        """Client address for the access log.

        Behind a trusted reverse proxy the real client IP is taken from the
        proxy headers and shown as "<client> via <proxy>".
        """
        peer = self.client_address[0]
        client = self._client_ip(peer)
        # Show IPv4 clients of a dual stack socket as "a.b.c.d" instead of "::ffff:a.b.c.d".
        peer_display = str(_parse_ip(peer) or peer)
        return peer_display if client in (peer, peer_display) else f"{client} via {peer_display}"

    def _client_ip(self, peer: str) -> str:
        """Resolve the client IP, using proxy headers only from trusted proxies.

        Every client can send its own X-Forwarded-For header, so the header is
        only used if the connection comes from a trusted proxy. The list
        "client, proxy1, proxy2" is read from the right, trusted proxies are
        skipped, the first untrusted address is the client.
        """
        trusted = self.app.settings.trusted_proxies
        peer_ip = _parse_ip(peer)
        # Headers are missing if the request could not be parsed (e.g. timeout).
        headers = getattr(self, "headers", None)
        if not trusted or headers is None or peer_ip is None or not _is_trusted(peer_ip, trusted):
            return peer

        forwarded = [
            item for header in headers.get_all("X-Forwarded-For") or [] for item in header.split(",")
        ]
        if not forwarded and (real_ip := headers.get("X-Real-IP")):
            forwarded = [real_ip]  # nginx with "proxy_set_header X-Real-IP $remote_addr;"

        client = peer_ip
        for item in reversed(forwarded):
            ip = _parse_ip(item)
            if ip is None:
                break  # invalid entry, do not trust anything left of it
            client = ip
            if not _is_trusted(ip, trusted):
                break
        return str(client)

    @override
    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 (name defined by base class)
        # Route access logs through logging (DEBUG) instead of writing them to stderr.
        logger.debug("%s - %s", self.address_string(), format % args)


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------


def run_healthcheck(settings: Settings) -> int:
    """Call /healthcheck of the locally running service.

    Returns:
        0 if the service answered with HTTP 200, otherwise 1.
    """
    # A wildcard listen address is not a valid target, use loopback instead.
    host = {"": "127.0.0.1", "0.0.0.0": "127.0.0.1", "::": "::1"}.get(settings.http_host, settings.http_host)
    scheme = "https" if settings.ssl_enabled else "http"
    url = f"{scheme}://{format_host(host)}:{settings.http_port}/healthcheck"

    # Ignore *_proxy environment variables, the check must hit the local service.
    handlers: list[urllib.request.BaseHandler] = [urllib.request.ProxyHandler({})]
    if settings.ssl_enabled:
        # Local self-check only: the certificate is issued for the public
        # hostname (or self-signed), so it cannot be verified for loopback.
        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        handlers.append(urllib.request.HTTPSHandler(context=context))
    opener = urllib.request.build_opener(*handlers)

    try:
        with opener.open(url, timeout=HEALTHCHECK_TIMEOUT) as response:
            healthy = response.status == HTTPStatus.OK
    except OSError as exc:  # includes URLError, HTTPError and timeouts
        logger.error("Healthcheck %s failed: %s", url, exc)
        return 1
    return 0 if healthy else 1


def log_startup_info(settings: Settings) -> None:
    """Log the effective configuration."""
    logger.info("mcstatus-httpd %s (Python %s, mcstatus %s)",
                __version__, platform.python_version(), package_version("mcstatus"))

    if (java := settings.java) is not None:
        logger.info("Java server:    %s:%d (query port %d), shown as %s",
                    java.host, java.port, java.query_port, java.display_hostname)
    else:
        logger.info("Java server:    not configured, omitted from output")

    if (bedrock := settings.bedrock) is not None:
        logger.info("Bedrock server: %s:%d (transport %s), shown as %s",
                    bedrock.host, bedrock.port, bedrock.transport, bedrock.display_hostname)
    else:
        logger.info("Bedrock server: not configured, omitted from output")

    logger.info("Timeout: %gs, cache TTL: %gs", settings.timeout, settings.cache_ttl)
    logger.info("CORS allowed origins: %s", ", ".join(settings.cors_origins))
    logger.info("Trusted proxies: %s",
                ", ".join(map(str, settings.trusted_proxies)) or "none (X-Forwarded-For is ignored)")

    scheme = "https" if settings.ssl_enabled else "http"
    base_url = f"{scheme}://{format_host(settings.http_host)}:{settings.http_port}"
    logger.info("Status endpoint:      %s%s", base_url, settings.http_prefix or "/")
    logger.info("Healthcheck endpoint: %s%s/healthcheck", base_url, settings.http_prefix)
    if settings.http_prefix:
        logger.info("Healthcheck endpoint: %s/healthcheck", base_url)
    if settings.avatar_enabled:
        logger.info("Avatar endpoint:      %s%s/avatar/<name>[?type=TYPE][&size=PIXELS]",
                    base_url, settings.http_prefix)
        logger.info("Avatars: default %s %d px, allowed types %s, sizes %s, providers %s, 3D fallback to flat: %s",
                    settings.avatar_type, settings.avatar_image_size,
                    ",".join(settings.avatar_allowed_types), ",".join(map(str, settings.avatar_allowed_sizes)),
                    ", ".join(provider.label for provider in settings.avatar_providers),
                    "on" if settings.avatar_type_fallback else "off")
        logger.info("Avatar cache: %s%s, TTL %gs, max. entries: %s", settings.avatar_cache_type,
                    f" ({settings.avatar_cache_dir})" if settings.avatar_cache_type == "file" else "",
                    settings.avatar_cache_ttl, settings.avatar_cache_max_entries or "unlimited")
        if not _uses_player_id(settings):
            logger.info("Player UUIDs: not needed (no avatar provider uses {id})")
        elif not settings.player_uuid_lookup:
            logger.info("Player UUIDs: lookup disabled, {id} = player name")
        else:
            logger.info("Player UUIDs: providers %s, cache %s%s, TTL %gs, max. entries: %s",
                        ", ".join(settings.player_uuid_providers), settings.player_uuid_cache_type,
                        f" ({settings.player_uuid_cache_file})" if settings.player_uuid_cache_type == "file" else "",
                        settings.player_uuid_cache_ttl, settings.player_uuid_cache_max_entries or "unlimited")
        for avatar_type in settings.avatar_allowed_types:
            if not any(avatar_type in provider.templates for provider in settings.avatar_providers):
                logger.warning("Avatars: no provider for type %s", avatar_type)
        if not settings.avatar_tls_verify:
            logger.warning("Avatars: TLS certificate verification disabled for own URL templates")
        if not settings.avatar_online_only:
            logger.warning("Avatars: available for any player name, not only for online players")
            if not settings.avatar_cache_max_entries:
                logger.warning("Avatars: unlimited cache for any player name, random names can fill the cache")
    else:
        logger.info("Avatars: disabled")


def main(argv: Sequence[str] | None = None) -> int:
    """Run the application and return the process exit code."""
    settings, healthcheck = parse_settings(argv)
    setup_logging(settings.loglevel)

    if healthcheck:
        return run_healthcheck(settings)

    log_startup_info(settings)

    try:
        server = StatusHTTPServer(settings)
    except OSError as exc:  # includes port in use, missing TLS files and ssl.SSLError
        logger.error("Cannot start server: %s", exc)
        return 1

    def request_shutdown(signum: int, _frame: object) -> None:
        logger.info("Received %s, shutting down", signal.Signals(signum).name)
        # shutdown() blocks until serve_forever() returns, so it must not be
        # called from the main thread that runs serve_forever().
        threading.Thread(target=server.shutdown, daemon=True).start()

    # Docker sends SIGTERM on "docker stop" (or SIGINT, see STOPSIGNAL in the
    # Dockerfile), Ctrl+C sends SIGINT. Both stop the server gracefully.
    signal.signal(signal.SIGTERM, request_shutdown)
    signal.signal(signal.SIGINT, request_shutdown)

    with server:
        logger.info("Server started")
        server.serve_forever()

    logger.info("Server stopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
