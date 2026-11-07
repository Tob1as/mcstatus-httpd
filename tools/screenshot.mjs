// Screenshot of a web page, e.g. the website examples in the test environment (tests/website) or
// a status box in a forum (README screenshot). Optional: only one status box (incl. the WSC box
// frame), mouse over, dark mode, only one server and anonymized data (address, players, MOTD).
// Run without arguments for the help text. Needs Chrome, Chromium or Edge (see lib/browser.mjs).
import { writeFileSync } from 'node:fs';
import { parseArgs } from 'node:util';
import { launchBrowser, sleep } from './lib/browser.mjs';

const HELP = `Usage: node tools/screenshot.mjs <url> [options]

  --out <file>         PNG file (default: screenshot.png)
  --width <px>         viewport width in CSS pixels (default: 1400)
  --height <px>        viewport height (default: 1000), the page is captured completely anyway
  --scale <n>          device pixel ratio, 2 = sharp images e.g. for the README (default: 1)
  --dark               prefers-color-scheme: dark
  --lang <code>        browser language, e.g. de or de-DE (texts and date of the boxes)
  --box <n>            only the n-th status box of the page (1 = first, .mcstatusBox or .mcstatusMini),
                       in WSC incl. the box frame with title
  --padding <px>       extra space around the box, e.g. for a tooltip above it (default: 0)
  --hover <selector>   move the mouse over this element (tooltip), searched in the box first
  --only <server>      java or bedrock: removes the other server from the JSON (single server)
  --address <host>     show this address instead of the real one
  --player <name>      show this player instead of the real ones (avatar from mc-heads.net)
  --pixelate-motd      pixelate the MOTD (wsc-box.html, index.html)
  --wait <ms>          wait after loading, e.g. for avatars (default: 1500)

Examples:
  node tools/screenshot.mjs http://localhost:18092/s/full/wsc-box-mini.html --width 300 --box 1
  node tools/screenshot.mjs http://localhost:18092/s/live/wsc-box-mini.html --width 300 --box 1 \
       --only java --hover .mcstatusName --padding 30
  node tools/screenshot.mjs https://forum.example.com/ --box 1 --scale 2 --address demo.mcstatus.io \\
       --player PassTheMayo --pixelate-motd --out examples/wsc-box.png`;

const { values: options, positionals } = parseArgs({
  allowPositionals: true,
  options: {
    out: { type: 'string', default: 'screenshot.png' },
    width: { type: 'string', default: '1400' },
    height: { type: 'string', default: '1000' },
    scale: { type: 'string', default: '1' },
    dark: { type: 'boolean' },
    lang: { type: 'string' },
    box: { type: 'string' },
    padding: { type: 'string', default: '0' },
    hover: { type: 'string' },
    only: { type: 'string' },
    address: { type: 'string' },
    player: { type: 'string' },
    'pixelate-motd': { type: 'boolean' },
    wait: { type: 'string', default: '1500' },
    help: { type: 'boolean', short: 'h' },
  },
});
const [url] = positionals;
if (!url || options.help) {
  console.log(HELP);
  process.exit(url || options.help ? 0 : 1);
}
if (options.only && !['java', 'bedrock'].includes(options.only)) {
  console.error('--only must be java or bedrock');
  process.exit(1);
}

const browser = await launchBrowser({
  width: Number(options.width), height: Number(options.height), scale: Number(options.scale),
}).catch((error) => {
  console.error(error.message);
  process.exit(1);
});
try {
  if (options.dark) {
    await browser.send('Emulation.setEmulatedMedia', { features: [{ name: 'prefers-color-scheme', value: 'dark' }] });
  }
  if (options.lang) {
    // navigator.language(s) and Accept-Language header, plus the locale for date formats.
    const { userAgent } = await browser.send('Browser.getVersion');
    await browser.send('Network.setUserAgentOverride', { userAgent, acceptLanguage: options.lang });
    await browser.send('Emulation.setLocaleOverride', { locale: options.lang });
  }
  if (options.only) {
    // Removes the other server from every status JSON the page loads.
    const other = options.only === 'java' ? 'bedrock' : 'java';
    await browser.send('Page.addScriptToEvaluateOnNewDocument', { source: `
      const originalFetch = window.fetch;
      window.fetch = async (...args) => {
        const response = await originalFetch(...args);
        const data = await response.clone().json().catch(() => null);
        if (!data || !('java' in data || 'bedrock' in data)) return response;
        delete data[${JSON.stringify(other)}];
        return new Response(JSON.stringify(data), { status: response.status, headers: { 'Content-Type': 'application/json' } });
      };` });
  }

  await browser.send('Page.navigate', { url });
  // Wait until the boxes show data or a message (or the page has no status box at all).
  for (let i = 0; i < 60; i++) {
    await sleep(300);
    const ready = await browser.evaluate(`document.readyState === 'complete' && (
      !document.querySelector('.mcstatusBox, .mcstatusMini')
      || !!document.querySelector('.mcstatusServer:not([hidden])')
      || [...document.querySelectorAll('.mcstatusMessage')].some((m) => !m.hidden && !/load/i.test(m.textContent)))`)
      .catch(() => false);
    if (ready) break;
  }
  await sleep(Number(options.wait));

  // Stop the automatic refresh of the boxes (it would undo the changes below), then anonymize.
  await browser.evaluate(`(async (address, player, pixelate) => {
    window.fetch = () => new Promise(() => {});
    for (const box of document.querySelectorAll('.mcstatusBox, .mcstatusMini')) {
      if (address) {
        box.querySelectorAll('[data-field="address"]').forEach((el) => { el.textContent = address; });
        box.querySelectorAll('.mcstatusName').forEach((el) => {
          if (el.dataset.name) {
            el.dataset.name = el.dataset.name.replace(/^.*(?=:\\d+$)/, address);  // tooltip "host:port"
          }
          if (el.dataset.title && el.textContent !== el.dataset.title) {
            el.textContent = address;  // mini box with one server shows the address instead of the name
          }
        });
      }
      if (player) {
        const images = [];
        box.querySelectorAll('.mcstatusAvatar').forEach((button) => {
          button.dataset.name = player;
          button.setAttribute('aria-label', player);
          const img = button.querySelector('img');
          if (img) {
            // Same image types as mcstatus-httpd (mc-heads), by the type parameter of the avatar URL.
            const type = new URL(img.src, location.href).searchParams.get('type') || 'head';
            const path = { head: 'avatar', body: 'player', head3d: 'head', body3d: 'body' }[type] || 'avatar';
            img.alt = player;
            img.loading = 'eager';
            img.src = 'https://mc-heads.net/' + path + '/' + encodeURIComponent(player) + '/64' + (type === 'head3d' ? '/nohelm' : '') + '.png';
            images.push(img.decode().catch(() => {}));
          }
        });
        // Names as text (avatars disabled or not available).
        box.querySelectorAll('.mcstatusAvatars > span').forEach((el) => { el.textContent = player; });
        box.querySelectorAll('[data-field="playerList"], .mcstatusPlayerList').forEach((el) => {
          if (!el.querySelector('.mcstatusAvatars') && el.textContent.trim()) {
            el.textContent = player;
          }
        });
        await Promise.all(images);
      }
      if (pixelate) {
        // Draw the MOTD into a canvas, scale it down and up again (mosaic of 4 px blocks).
        const block = 4;
        const scale = devicePixelRatio;
        box.querySelectorAll('[data-field="motd"]').forEach((el) => {
          if (el.hidden || !el.textContent.trim()) return;
          const cs = getComputedStyle(el);
          const rect = el.getBoundingClientRect();
          const w = Math.ceil(rect.width), h = Math.ceil(rect.height);
          const right = cs.textAlign === 'right' || cs.textAlign === 'end';
          const canvas = document.createElement('canvas');
          canvas.width = w * scale;
          canvas.height = h * scale;
          // max-width: the fixed size must not squeeze the label column of the list.
          canvas.style.cssText = 'width:' + w + 'px;max-width:100%;height:auto;display:block;' + (right ? 'margin-left:auto' : '');
          const ctx = canvas.getContext('2d');
          ctx.scale(scale, scale);
          ctx.font = cs.font;
          ctx.fillStyle = cs.color;
          ctx.textAlign = right ? 'right' : 'left';
          ctx.textBaseline = 'top';
          const fontSize = parseFloat(cs.fontSize);
          const lineHeight = parseFloat(cs.lineHeight) || fontSize * 1.5;
          const lines = [];
          let line = '';
          for (const word of el.textContent.trim().split(/\\s+/)) {
            const next = line ? line + ' ' + word : word;
            if (ctx.measureText(next).width > w && line) { lines.push(line); line = word; } else { line = next; }
          }
          if (line) lines.push(line);
          lines.forEach((text, i) => ctx.fillText(text, right ? w : 0, i * lineHeight + (lineHeight - fontSize) / 2));
          const small = document.createElement('canvas');
          small.width = Math.ceil(canvas.width / (block * scale));
          small.height = Math.ceil(canvas.height / (block * scale));
          small.getContext('2d').drawImage(canvas, 0, 0, small.width, small.height);
          ctx.setTransform(1, 0, 0, 1, 0, 0);
          ctx.clearRect(0, 0, canvas.width, canvas.height);
          ctx.imageSmoothingEnabled = false;
          ctx.drawImage(small, 0, 0, small.width * block * scale, small.height * block * scale);
          el.replaceChildren(canvas);
        });
      }
    }
  })(${JSON.stringify(options.address ?? '')}, ${JSON.stringify(options.player ?? '')}, ${!!options['pixelate-motd']})`);
  await sleep(500);

  // Mouse over (in the viewport, so the element is scrolled into view first).
  const boxIndex = options.box ? Number(options.box) - 1 : -1;
  const boxExpr = `document.querySelectorAll('.mcstatusBox, .mcstatusMini')[${boxIndex}]`;
  if (boxIndex >= 0 && !(await browser.evaluate(`!!${boxExpr}`))) {
    throw new Error(`status box ${options.box} not found`);
  }
  if (options.hover) {
    const position = await browser.evaluate(`(() => {
      const box = ${boxIndex >= 0 ? boxExpr : 'null'};
      const el = box?.querySelector(${JSON.stringify(options.hover)}) || document.querySelector(${JSON.stringify(options.hover)});
      if (!el) return null;
      el.scrollIntoView({ block: 'center' });
      const r = el.getBoundingClientRect();
      return { x: r.x + r.width / 2, y: r.y + r.height / 2 };
    })()`);
    if (!position) {
      throw new Error(`--hover: element ${options.hover} not found`);
    }
    await browser.send('Input.dispatchMouseEvent', { type: 'mouseMoved', ...position });
    await sleep(300);
  }

  // Area: one box (WSC: incl. the frame "section.box" with title) or the whole page.
  const clip = await browser.evaluate(`(() => {
    const box = ${boxIndex >= 0 ? boxExpr : 'null'};
    if (!box) {
      return { x: 0, y: 0, width: document.documentElement.scrollWidth, height: document.documentElement.scrollHeight };
    }
    const r = (box.closest('section.box') || box).getBoundingClientRect();
    const p = ${Number(options.padding)};
    return { x: Math.max(0, Math.floor(r.x + scrollX - p)), y: Math.max(0, Math.floor(r.y + scrollY - p)),
             width: Math.ceil(r.width + 2 * p), height: Math.ceil(r.height + 2 * p) };
  })()`);
  writeFileSync(options.out, await browser.screenshot(clip));
  console.log(`saved ${options.out} (${clip.width}x${clip.height} CSS px, scale ${options.scale})`);
} finally {
  await browser.close();
}
