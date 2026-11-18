# Test environment with a local Minecraft demo server

Runs mcstatus-httpd (built from this repository) against a local fake Minecraft server, the [demo-server of mcstatus.io](https://github.com/mcstatus-io/demo-server) (the software behind `demo.mcstatus.io`). It answers Java status, Java query and Bedrock status (RakNet) with the values of a config file, so mcstatus-httpd can be tested with defined data (many players, no query, server offline, ...) without a real Minecraft server.  
Requires only Docker (with Docker Compose), no Go, Python or Minecraft server.

```sh
docker compose -f tests/demo-server/docker-compose.yml up -d --build
```

Open http://localhost:18093/mcstatus: the status JSON of mcstatus-httpd.

Stop and remove (incl. the built images):

```sh
docker compose -f tests/demo-server/docker-compose.yml down --rmi all
```

## How it works

* `demo-server`: built with the [`Dockerfile`](Dockerfile) in this folder. The source code is downloaded as GitHub archive and compiled into a static binary, the image is based on `scratch` and runs as user `nobody` (65534). The config file is mounted from [`config/`](config/) to `/app/config.yml`.
* `mcstatus-httpd`: queries the demo server via its service name `demo-server` (Java and Bedrock) and shows `minecraft.example.com` as hostname (`MINECRAFT_*_SERVER_OVERWRITE`). `CACHE_TTL=0`, so every request queries the demo server again. Avatars are enabled (loaded from the providers, needs internet).

| Port of the demo server | Protocol |
|-------------------------|----------|
| 25565/tcp               | Java status |
| 25565/udp               | Java query |
| 19132/udp               | Bedrock status (RakNet only, no NetherNet) |
| 8192/tcp                | Votifier (only in `default`) |

The ports are not published to the host. To query the demo server from the host (e.g. with the `mcstatus` CLI), uncomment `ports` in the [`docker-compose.yml`](docker-compose.yml) (25566 and 19133, so they do not collide with a local Minecraft server).

## Configs

| Config         | Content |
|----------------|---------|
| `default`      | copy of `config.example.yml` of the demo server: Java 50-99 of 100 players (random on every request), 3 names, Forge mods, plugin, Bedrock 50-99 of 100 players, Votifier |
| `online`       | both online with fixed values, 3 Java players |
| `full`         | 20/20 Java players (all names via query), 10/10 Bedrock, colored MOTD |
| `empty`        | both online, nobody playing |
| `sample`       | Java without query (status fallback): 47 online, only 12 names plus a fake entry with the NIL UUID (`... and 35 more`, like some server plugins), which mcstatus-httpd skips; `brand`/`map` are `null` |
| `java-only`    | Bedrock is not started (with the docker-compose.yml: Java online, Bedrock offline) |
| `bedrock-only` | Java is not started (with the docker-compose.yml: Java offline, Bedrock online) |
| `long`         | long version, two-line MOTD, plugin list and map name |

The names are the same as the scenarios of the [website test environment](../website/README.md#scenarios), the content is similar.

Select a config with the environment variable `DEMO_SERVER_CONFIG` (default: `default`), `up -d` recreates the container when the value changes:

```sh
# bash
DEMO_SERVER_CONFIG=full docker compose -f tests/demo-server/docker-compose.yml up -d
```

```powershell
# PowerShell
$env:DEMO_SERVER_CONFIG="full"; docker compose -f tests/demo-server/docker-compose.yml up -d
```

Server offline: `docker compose -f tests/demo-server/docker-compose.yml stop demo-server` (start again with `start demo-server`).

Own configs: add a file `config/<name>.yml` (format: [`config.example.yml`](https://github.com/mcstatus-io/demo-server/blob/main/config.example.yml) of the demo server) and select it with `DEMO_SERVER_CONFIG=<name>`. Notes:

* Missing sections are disabled (`enable: false`), missing numbers are 0.
* Player counts: `random: true` = random number from `min` to `max - 1` on every request, otherwise `value`.
* Query and status both send the `sample` list as player names.
* `motd` of Java is a [chat component](https://minecraft.wiki/w/Text_component_format) (`text`, `color`, `bold`, `extra`, ...), `\n` in `text` is a line break.
* `line_2` of the Bedrock MOTD is the map (level) name.
* Quote values that contain `: ` (YAML), e.g. `name: 'Paper 1.21.4-232 (MC: 1.21.4)'`.
* An optional `server-icon.png` in `/app` (64x64) is sent as favicon of the Java status (not used by mcstatus-httpd).

## Test with unreleased mcstatus

[`docker-compose.mcstatus-git.yml`](docker-compose.mcstatus-git.yml) is an override for the docker-compose.yml: it builds mcstatus-httpd with [mcstatus](https://github.com/py-mine/mcstatus) from GitHub (default: `main` branch) instead of the released version of `requirements.txt` ([`mcstatus-git.Dockerfile`](mcstatus-git.Dockerfile)). So changes of mcstatus can be tested with the current `mcstatus-httpd.py` before they are released. Everything else stays the same (demo server, configs, port 18093).

```sh
docker compose -f tests/demo-server/docker-compose.yml -f tests/demo-server/docker-compose.mcstatus-git.yml up -d --build
```

Stop and remove: the same files with `down --rmi all`.

* Other branch, tag or commit of mcstatus: environment variable `MCSTATUS_REF`, e.g. `MCSTATUS_REF=v15.0.0`.
* The build output shows the tested mcstatus commit (`--progress=plain`). Docker downloads the archive again on every build; if an old state is used anyway, build with `--no-cache`.
* mcstatus from GitHub reports the version `0.0.0` in the log, that is expected.
* Compare with the released mcstatus: start again without the override file (`CACHE_TTL=0`, so the JSON is current at once).
* The demo server only supports RakNet for Bedrock. For NetherNet a real Bedrock server is needed, e.g. set `MINECRAFT_BEDROCK_SERVER` in an own override file.

## Demo server image

The [`Dockerfile`](Dockerfile) can also be built alone:

```sh
docker build --build-arg REF=main -t mcstatus-demo-server tests/demo-server
```

* `REF`: branch, tag or commit SHA of [mcstatus-io/demo-server](https://github.com/mcstatus-io/demo-server) (default: `main`). In the docker-compose.yml via the environment variable `DEMO_SERVER_REF`.
* `GO_VERSION`: version of the Go build image (default: `1.27` = latest 1.27.x patch).
* The image contains `config.example.yml` as `/app/config.yml`, the server reads `config.yml` (and `server-icon.png`) from its working directory `/app`.

Fix applied during the build: the full stat response of the query sends the key `game_type`, vanilla Minecraft (and Python mcstatus) uses `gametype`. Without the fix the query fails in mcstatus-httpd and it always uses the status fallback (probably also the reason why the query of `demo.mcstatus.io` fails). The fix is a `sed` in the Dockerfile and does nothing once it is fixed upstream.
