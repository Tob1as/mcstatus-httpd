# Development tools

Helper scripts for the development of mcstatus-httpd. They are not needed to run mcstatus-httpd.

Requirements:
* [Node.js](https://nodejs.org/) >= 22 (no npm packages needed)
* For PNG/WebP files and screenshots: Chrome, Chromium or Edge. It is found automatically (Windows, macOS, Linux), otherwise set the environment variable `BROWSER` to its path, e.g. `BROWSER=/usr/bin/chromium node tools/screenshot.mjs ...`.  
  The browser runs without window and with an empty temporary profile (no cookies or logins of your normal browser).

The scripts can be started from any directory.

| Script | Purpose |
|--------|---------|
| [`make-icons.mjs`](make-icons.mjs) | generates the icons of [`examples/icons`](../examples/icons/) |
| [`screenshot.mjs`](screenshot.mjs) | screenshot of a page or of a single status box, optionally anonymized (e.g. for the README) |
| [`wsc-styles.mjs`](wsc-styles.mjs) | measures the styles of a WSC page (for the WSC test page of the test environment) |
| [`lib/browser.mjs`](lib/browser.mjs) | shared code: finds and starts the browser, controls it via the [DevTools protocol](https://chromedevtools.github.io/devtools-protocol/) |

The test environment for the website examples (live and mock data) is in [`tests/website`](../tests/website/README.md).

## make-icons.mjs

```sh
node tools/make-icons.mjs                               # only SVG files (no browser needed)
node tools/make-icons.mjs --png                         # additionally PNG files (all sizes)
node tools/make-icons.mjs --webp                        # additionally WebP files (all sizes)
node tools/make-icons.mjs --preview icons-preview.png   # additionally a preview on light and dark background
```

The options can be combined, e.g. `--png --webp`. After a change of the SVG drawing run it with `--png`, so the PNG files in the repository match again.

All icons are drawn by this script (no third-party graphics):

* `minecraft-block-icon.svg`: isometric pixel-art grass block. Each face is an 8x8 pattern of letters (`L`/`M`/`D` = light/main/dark grass, `l`/`m`/`d` = dirt), mapped onto the face with an SVG `matrix` transform. The side faces are darkened (shading).
* `minecraft-block-icon-<size>.png` (with `--png`): the block as PNG in 16, 32, 64, 128, 256 and 512 px with transparent background (rendered by the browser), e.g. as box icon or favicon.
* `minecraft-block-icon-<size>.webp` (with `--webp`, not in the repository): the same as lossless WebP (converted from the rendered PNG, color profile removed), mostly smaller than the PNG (except 512 px).
* `status-dot-green.svg`, `status-dot-red.svg`, `status-dot-mixed.svg` (half green / half red, used in the README), each also as `-plain.svg` without the light ring, and `plus.svg`.

Colors and patterns are defined at the top of the script (`colors`, `top`, `side`).

## screenshot.mjs

```sh
node tools/screenshot.mjs <url> [options]
node tools/screenshot.mjs --help
```

| Option | Description |
|--------|-------------|
| `--out <file>` | PNG file (default `screenshot.png`) |
| `--width <px>` / `--height <px>` | viewport in CSS pixels (default 1400 x 1000), the page is captured completely anyway |
| `--scale <n>` | device pixel ratio, `2` = sharp images e.g. for the README |
| `--dark` | dark mode (`prefers-color-scheme: dark`) |
| `--lang <code>` | browser language, e.g. `de` or `en-US` (texts and date of the boxes on pages without `<html lang>`) |
| `--box <n>` | only the n-th status box of the page (`.mcstatusBox` of `wsc-box.html`/`index.html` or `.mcstatusMini` of `wsc-box-mini.html`), in WSC incl. the box frame with title |
| `--padding <px>` | extra space around the box, e.g. for a tooltip above it |
| `--hover <selector>` | moves the mouse over an element (tooltip), e.g. `.mcstatusAvatar`, `.mcstatusName`, `.mcstatusDot` |
| `--only java\|bedrock` | removes the other server from the status JSON (single server view) |
| `--address <host>` | shows this address instead of the real one (also in the tooltips of the mini box) |
| `--player <name>` | shows this player instead of the real ones (avatar from mc-heads.net, also names as text and tooltips) |
| `--pixelate-motd` | pixelates the MOTD |
| `--wait <ms>` | waits after loading, e.g. for avatars (default 1500) |

The script waits until the boxes show data, then stops their automatic refresh (so the changes are not undone) and applies the options.

Examples with the [test environment](../tests/website/README.md):

```sh
# mini box with 20 players, as in a narrow sidebar
node tools/screenshot.mjs http://localhost:18092/s/full/wsc-box-mini.html --width 300 --box 1 --out mini.png
# status page in dark mode on a phone
node tools/screenshot.mjs http://localhost:18092/s/live/index.html --width 390 --dark --out phone.png
# only Java, with the tooltip of the address
node tools/screenshot.mjs http://localhost:18092/s/live/wsc-box-mini.html --width 300 --box 1 --only java --hover .mcstatusName --padding 30
```

README screenshot `examples/wsc-box.png`: the box in the sidebar of the WSC test page, scenario `online`, English, light, mouse over the avatar of Notch:

```sh
node tools/screenshot.mjs "http://localhost:18092/wsc/sidebar/online/wsc-box.html?lang=en&light" --box 1 --scale 2 --lang en-US --hover ".mcstatusAvatar[data-name=Notch]" --wait 4000 --out examples/wsc-box.png
```

Screenshot of a box in your own forum (WSC), with demo address, demo player and pixelated MOTD:

```sh
node tools/screenshot.mjs https://forum.example.com/ --box 1 --scale 2 --address demo.mcstatus.io --player PassTheMayo --pixelate-motd --out wsc-box.png
```

Note: a tooltip above an element at the very top of the page cannot be captured (outside the page).

## wsc-styles.mjs

```sh
node tools/wsc-styles.mjs https://forum.example.com/ --out wsc-styles.json
```

Measures the computed styles of a WSC page in the light and the dark color scheme: page header, content and page title, sidebar box (incl. box image), footer boxes, page footer, lists (`dl.plain.dataList`), labels (`.badge.label.green/.red`) and the WSC color variables (`--wcf...`). Parts that are not on the page are `null`, e.g. the footer boxes or a red label (only shown while a server is offline).

Use it to check or update [`tests/website/wsc/wsc.css`](../tests/website/wsc/wsc.css), the approximation of the WSC default style of the [WSC test page](../tests/website/README.md#wsc-test-page), e.g. after a WSC update or for another style. Options: `--out <file.json>` (otherwise printed), `--wait <ms>` (waiting time after loading, default 5000).
