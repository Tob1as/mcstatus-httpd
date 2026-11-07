# Test environment for the website examples

Shows the website examples of [`examples/`](../../examples/) with live data or mock data, e.g. to check a change of the HTML/CSS in different situations (many players, offline server, long names, ...).  
Requires only Docker (with Docker Compose), no Python or Minecraft server.

```sh
docker compose -f tests/website/docker-compose.yml up -d --build
```

Open http://localhost:18092/: an overview with links to all scenarios and pages.

Stop and remove (incl. the built image):

```sh
docker compose -f tests/website/docker-compose.yml down --rmi all
```

## How it works

* `mcstatus-httpd`: built from this repository (current code), queries the demo servers of [mcstatus.io](https://mcstatus.io/) and delivers the avatars of all scenarios (`AVATAR_ONLINE_ONLY=0`, so every player name of the mock data gets its avatar).
* `web` (nginx with [njs](https://nginx.org/en/docs/njs/)): serves the pages of `examples/` read-only. Under `/s/<scenario>/<page>.html` it replaces `MCSTATUS_URL` with `/s/<scenario>/mcstatus` on the fly and sets `REFRESH_SECONDS` to 10. The files in `examples/` stay unchanged, changes are visible after a reload of the page.

| URL                          | Data |
|------------------------------|------|
| `/s/live/mcstatus`           | real mcstatus-httpd (demo servers) |
| `/s/random/mcstatus`         | new random JSON on every request, see [`mock.js`](mock.js) |
| `/s/error/mcstatus`          | HTTP 500 (error message of the boxes) |
| `/s/<name>/mcstatus`         | fixed JSON of [`scenarios/<name>.json`](scenarios/) |
| `/s/<scenario>/mcstatus/avatar/<name>` | avatar via mcstatus-httpd |
| `/avatar-check.html?u=<name>` | [avatar check](#avatar-check) |
| `/wsc/<sidebar\|footer\|page>/<scenario>/<page>.html` | [WSC test page](#wsc-test-page) with a WSC box |

Example: http://localhost:18092/s/full/wsc-box-mini.html = mini box with 20 Java players.

Under `/s/...` the WSC boxes are shown without the CSS of WSC, so they look plain. `index.html` brings its own CSS. For the look in a forum use the [WSC test page](#wsc-test-page).

## Scenarios

| Scenario       | Content |
|----------------|---------|
| `live`         | real data of the demo servers |
| `random`       | Java 0-20 players (more than 12: status fallback with only 12 names), sometimes a Geyser player (`.BedrockSteve`, no avatar → name as text), Bedrock 0-10 players, each server offline in about every 8th request |
| `online`       | both online, 3 Java players |
| `full`         | 20/20 Java players (avatars wrap), 10/10 Bedrock |
| `sample`       | Java without Query: 47 online, only 12 names, `brand`/`map` are `null` |
| `empty`        | both online, nobody playing |
| `offline`      | both offline |
| `mixed`        | Java online, Bedrock offline |
| `java-only`    | only Java configured (mini box shows the address instead of the server name) |
| `bedrock-only` | only Bedrock configured |
| `long`         | long hostnames, MOTD, plugin list and names, names without avatar |
| `error`        | HTTP 500 |

Own scenarios: add a file `scenarios/<name>.json` (lowercase letters, digits and `-`), it is available at once under `/s/<name>/...` (no restart needed). The format is the JSON of mcstatus-httpd, see "Example Output" in the [README](../../README.md#example-output).

## WSC test page

Shows `wsc-box.html` or `wsc-box-mini.html` on a page in the look of a WSC forum (default style):

* `sidebar`: in the sidebar (box with image: the Minecraft block of `examples/icons`), below it a statistics box for comparison
* `footer`: in the footer boxes, next to a statistics box
* `page`: as own page (WSC CMS page with the box code as content), sidebar with the statistics box

With `sidebar` and `footer` the content area shows placeholder text (Lorem ipsum), so the page looks like a normal forum page.

* http://localhost:18092/wsc/sidebar/live/wsc-box.html
* http://localhost:18092/wsc/footer/full/wsc-box-mini.html
* http://localhost:18092/wsc/page/mixed/wsc-box.html

Links in the header of the page switch between the positions, color scheme and language:

* `?light` / `?dark`: color scheme, without it the setting of the device (like "automatic" in WSC)
* `?lang=de` / `?lang=en`: language of the forum user (WSC writes it into `<html lang>`, the boxes use it), without it the language of the browser

How it works: [`wsc/frame.html`](wsc/frame.html) is the page, nginx includes the example file there unchanged with SSI (`<!--# include virtual="/s/<scenario>/<page>" -->`, so `MCSTATUS_URL` of the scenario is replaced as usual). [`wsc/wsc.css`](wsc/wsc.css) is an own approximation of the WSC default style (no code of WSC, the values were measured on a WSC page with [`tools/wsc-styles.mjs`](../../tools/README.md#wsc-stylesmjs)): page frame, boxes, `dl.plain.dataList` and the labels `.badge.label.green/.red`, light and dark. Own forum styles look different.

## Avatar check

[`avatar-check.html`](avatar-check.html) shows all avatar variants of the providers (mc-heads, minotar, crafthead) for one player side by side, e.g. to compare the providers or to check a new provider URL. URLs used by mcstatus-httpd are marked with `*`.  
Open it via the test environment (http://localhost:18092/avatar-check.html?u=Notch, last row = avatars via mcstatus-httpd) or directly as file in the browser (provider rows only).

Note: the browser loads the provider images directly, so the providers see your IP address (unlike mcstatus-httpd, which loads them on the server).
