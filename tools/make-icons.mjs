// Generates the icons of examples/icons/ (own drawing, no third-party graphics).
// Usage: node tools/make-icons.mjs [--png] [--webp] [--preview <file.png>]
//   minecraft-block-icon.svg          isometric pixel-art grass block (8x8 pixels per face)
//   status-dot-green.svg              green status dot (online)
//   status-dot-red.svg                red status dot (offline)
//   status-dot-mixed.svg              half green / half red status dot (online/offline), used in the README
//   status-dot*-plain.svg             the same status dots without the light ring (same outer size)
//   plus.svg                          "+" between the icons in the README
//   --png                             additionally minecraft-block-icon-<size>.png (16-512 px, transparent)
//   --webp                            additionally minecraft-block-icon-<size>.webp: lossless WebP
//                                     (same pixels as the PNGs, not in the repository)
//   --preview <file.png>              additionally an image of all icons on light and dark background
// The SVG files are written as text (no browser needed), PNG/WebP/preview are rendered by
// Chrome/Chromium/Edge (see lib/browser.mjs).
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { parseArgs } from 'node:util';
import { findBrowser, launchBrowser, sleep } from './lib/browser.mjs';

const { values: options } = parseArgs({
  options: { png: { type: 'boolean' }, webp: { type: 'boolean' }, preview: { type: 'string' } },
});
const dir = join(dirname(fileURLToPath(import.meta.url)), '..', 'examples', 'icons');
mkdirSync(dir, { recursive: true });
const write = (name, content) => {
  writeFileSync(join(dir, name), content);
  console.log(`saved examples/icons/${name}`);
};

// ---- Block -------------------------------------------------------------------
// Colors and pixel pattern: uppercase = grass, lowercase = dirt (L/l light, M/m main, D/d dark).
const colors = {
  L: '#7fbf4d', M: '#5e9e3a', D: '#487e2a',  // grass
  l: '#a07a55', m: '#85603f', d: '#694a30',  // dirt
};
const top = ['MLMMDMLM', 'MMDLMMMD', 'LMMMMDML', 'MDMLMMMM', 'MMMMDLMD', 'DLMMMMLM', 'MMDMLMMM', 'LMMDMMDM'];
const side = ['MLMMLMDM', 'DMmMDmMM', 'mlmdmMml', 'mmdmlmmd', 'dmmmmdmm', 'mlmdmmlm', 'mmmlmdmm', 'dmlmmmmd'];
const sideMirrored = side.map((row) => [...row].reverse().join(''));

// One face: 8x8 unit squares, mapped onto the face by a matrix (isometric projection).
// A base polygon in the main color below the squares hides the anti-aliasing seams between them,
// an optional black polygon on top darkens the face (shading of the sides).
const face = (matrix, rows, base, points, shade) => {
  const paths = {};
  rows.forEach((row, y) => [...row].forEach((ch, x) => {
    (paths[ch] ??= []).push(`M${x} ${y}h1v1h-1z`);
  }));
  const squares = Object.entries(paths).map(([ch, d]) => `<path fill="${colors[ch]}" d="${d.join('')}"/>`).join('');
  return `<polygon fill="${base}" points="${points}"/>`
    + `<g transform="matrix(${matrix})">${squares}</g>`
    + (shade ? `<polygon fill="#000" fill-opacity="${shade}" points="${points}"/>` : '');
};

// viewBox 64x64: top face from (32,4) to (58,17), (32,30), (6,17); sides 30 units high.
write('minecraft-block-icon.svg', '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">'
  + '<title>Minecraft</title>'
  + face('3.25 1.625 -3.25 1.625 32 4', top, colors.M, '32,4 58,17 32,30 6,17', 0)
  + face('3.25 1.625 0 3.75 6 17', side, colors.m, '6,17 32,30 32,60 6,47', 0.12)
  + face('3.25 -1.625 0 3.75 32 30', sideMirrored, colors.m, '32,30 58,17 58,47 32,60', 0.3)
  + '</svg>\n');

// ---- Status icons (same colors as the status dot of the website examples) ------
const green = '#16a34a';
const red = '#dc2626';
// Default with a light ring around the dot; "plain" without the ring, the dot as large as the ring.
const dot = (color, plain) => (plain
  ? `<circle cx="32" cy="32" r="18" fill="${color}"/>`
  : `<circle cx="32" cy="32" r="18" fill="${color}" fill-opacity=".2"/><circle cx="32" cy="32" r="11" fill="${color}"/>`);
const status = {};
for (const [suffix, plain] of [['', false], ['-plain', true]]) {
  status[`status-dot-green${suffix}.svg`] = ['Status: Online', dot(green, plain)];
  status[`status-dot-red${suffix}.svg`] = ['Status: Offline', dot(red, plain)];
  // Half green (upper right), half red (lower left), dividing line from top left to bottom right.
  status[`status-dot-mixed${suffix}.svg`] = ['Status: Online/Offline', '<defs><clipPath id="g"><polygon points="0,0 64,0 64,64"/></clipPath>'
    + '<clipPath id="r"><polygon points="0,0 0,64 64,64"/></clipPath></defs>'
    + `<g clip-path="url(#g)">${dot(green, plain)}</g><g clip-path="url(#r)">${dot(red, plain)}</g>`];
}
for (const [name, [title, content]] of Object.entries(status)) {
  write(name, `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"><title>${title}</title>${content}</svg>\n`);
}
// "+" between block and status in the README: half as wide, same height (so all images align),
// neutral gray for light and dark mode.
write('plus.svg', '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 64"><title>plus</title>'
  + '<path fill="none" stroke="#8b949e" stroke-width="4" stroke-linecap="round" d="M16 24v16M8 32h16"/></svg>\n');

// ---- PNG/WebP + preview (browser, only on request) -----------------------------------
if (!options.png && !options.webp && !options.preview) {
  process.exit(0);
}
if (!findBrowser()) {
  console.error('No Chrome, Chromium or Edge found (set BROWSER), needed for --png, --webp and --preview.');
  process.exit(1);
}

const dataUrl = (name) => `data:image/svg+xml;base64,${readFileSync(join(dir, name)).toString('base64')}`;

// Removes the color profile (ICCP chunk) the browser embeds in WebP files (about 500 bytes, larger
// than the small icons themselves), the pixels stay the same. RIFF: 'RIFF' size 'WEBP', then chunks
// with 4 byte name, 4 byte length (little endian) and data padded to an even length.
const stripIccProfile = (webp) => {
  const chunks = [];
  for (let pos = 12; pos + 8 <= webp.length;) {
    const size = webp.readUInt32LE(pos + 4);
    const end = pos + 8 + size + (size % 2);
    const chunk = Buffer.from(webp.subarray(pos, end));
    const name = chunk.toString('ascii', 0, 4);
    if (name === 'VP8X') {
      chunk[8] &= ~0x20;  // flag "has ICC profile"
    }
    if (name !== 'ICCP') {
      chunks.push(chunk);
    }
    pos = end;
  }
  const body = Buffer.concat([Buffer.from('WEBP'), ...chunks]);
  const header = Buffer.alloc(8);
  header.write('RIFF', 0, 'ascii');
  header.writeUInt32LE(body.length, 4);
  return Buffer.concat([header, body]);
};
const browser = await launchBrowser({ width: 800, height: 600 }).catch((error) => {
  console.error(error.message);
  process.exit(1);
});
try {
  await browser.send('Emulation.setDefaultBackgroundColorOverride', { color: { r: 0, g: 0, b: 0, a: 0 } });
  const block = dataUrl('minecraft-block-icon.svg');

  for (const size of (options.png || options.webp) ? [16, 32, 64, 128, 256, 512] : []) {
    await browser.evaluate(`(async () => {
      document.body.style.margin = '0';
      const img = new Image(${size}, ${size});
      img.style.display = 'block';
      img.src = ${JSON.stringify(block)};
      await img.decode();
      document.body.replaceChildren(img);
    })()`);
    await sleep(100);
    const png = await browser.screenshot({ x: 0, y: 0, width: size, height: size });
    if (options.png) {
      write(`minecraft-block-icon-${size}.png`, png);
    }
    if (!options.webp) {
      continue;
    }

    // WebP from the PNG, so both have the same pixels. Chromium encodes WebP losslessly with quality 1.
    const webp = await browser.evaluate(`(async () => {
      const img = new Image();
      img.src = 'data:image/png;base64,${png.toString('base64')}';
      await img.decode();
      const canvas = document.createElement('canvas');
      canvas.width = ${size};
      canvas.height = ${size};
      canvas.getContext('2d').drawImage(img, 0, 0);
      return canvas.toDataURL('image/webp', 1);
    })()`);
    if (!webp.startsWith('data:image/webp')) {
      throw new Error('the browser cannot encode WebP');
    }
    write(`minecraft-block-icon-${size}.webp`, stripIccProfile(Buffer.from(webp.split(',')[1], 'base64')));
  }

  if (options.preview) {
    // Block + "+" + each status icon, on light and dark background (like GitHub).
    const rows = Object.keys(status).map((name) => [name, [block, dataUrl('plus.svg'), dataUrl(name)]]);
    const area = await browser.evaluate(`(async () => {
      document.body.style.cssText = 'margin:0;font:14px system-ui,sans-serif';
      const wrap = document.createElement('div');
      wrap.style.cssText = 'display:inline-grid;grid-template-columns:repeat(2,auto)';
      const images = [];
      for (const [bg, fg] of [['#ffffff', '#1f2328'], ['#0d1117', '#e6edf3']]) {
        const column = document.createElement('div');
        column.style.cssText = 'padding:16px 24px;background:' + bg + ';color:' + fg;
        for (const [name, urls] of ${JSON.stringify(rows)}) {
          const row = document.createElement('div');
          row.style.cssText = 'display:flex;align-items:center;margin:8px 0';
          urls.forEach((url, i) => {
            const img = new Image(i === 1 ? 40 : 80, 80);
            img.src = url;
            images.push(img.decode());
            row.append(img);
          });
          const label = document.createElement('span');
          label.textContent = name;
          label.style.marginLeft = '16px';
          row.append(label);
          column.append(row);
        }
        wrap.append(column);
      }
      document.body.replaceChildren(wrap);
      await Promise.all(images);
      const r = wrap.getBoundingClientRect();
      return { x: 0, y: 0, width: Math.ceil(r.width), height: Math.ceil(r.height) };
    })()`);
    await sleep(200);
    writeFileSync(options.preview, await browser.screenshot(area));
    console.log(`saved ${options.preview}`);
  }
} finally {
  await browser.close();
}
