// Measures the computed styles of a WSC page (light and dark color scheme), e.g. to check or update
// the approximation of the WSC default style in tests/website/wsc/wsc.css.
// Usage: node tools/wsc-styles.mjs <url> [--out <file.json>] [--wait <ms>]
// Needs Chrome, Chromium or Edge (see lib/browser.mjs). Without --out the JSON is printed.
import { writeFileSync } from 'node:fs';
import { parseArgs } from 'node:util';
import { launchBrowser, sleep } from './lib/browser.mjs';

const { values: options, positionals } = parseArgs({
  allowPositionals: true,
  options: { out: { type: 'string' }, wait: { type: 'string', default: '5000' }, help: { type: 'boolean', short: 'h' } },
});
const [url] = positionals;
if (!url || options.help) {
  console.log('Usage: node tools/wsc-styles.mjs <url> [--out <file.json>] [--wait <ms>]\n\n'
    + 'Example: node tools/wsc-styles.mjs https://forum.example.com/ --out wsc-styles.json');
  process.exit(url || options.help ? 0 : 1);
}

// Parts of a WSC page (first match of each selector). Selectors of WSC 6, a part not on the page is null.
const PARTS = {
  body: 'body',
  header: '.pageHeaderContainer',
  headerMenuLink: '.pageHeaderContainer .boxMenuLink',
  main: '.main',
  content: '.content',
  contentTitle: '.contentHeader h1.contentTitle, h1.contentTitle',
  sidebar: '.sidebar',
  sidebarBox: '.sidebar section.box',
  boxImage: '.sidebar .boxImage',
  boxImageImg: '.sidebar .boxImage img',
  boxTitle: '.sidebar .boxTitle',
  boxContent: '.sidebar .boxContent',
  footerBoxes: '.boxesFooterBoxes',
  footerBox: '.boxesFooterBoxes section.box',
  footerBoxTitle: '.boxesFooterBoxes .boxTitle',
  pageFooter: '.pageFooter',
  dataListDt: 'dl.plain.dataList dt',
  dataListDd: 'dl.plain.dataList dd',
  badge: '.badge',
  badgeGreen: '.badge.label.green',
  badgeRed: '.badge.label.red',
};
const PROPS = ['display', 'float', 'clear', 'width', 'height', 'max-width', 'margin', 'padding', 'background-color', 'color',
  'font-family', 'font-size', 'font-weight', 'line-height', 'border', 'border-radius', 'text-align', 'overflow', 'gap',
  'grid-template-columns', 'box-shadow'];
const VARIABLES = ['--wcfContentBackground', '--wcfContentText', '--wcfContentDimmedText', '--wcfContentBorderInner',
  '--wcfSidebarBackground', '--wcfSidebarText', '--wcfSidebarDimmedText', '--wcfSidebarHeadlineText', '--wcfSidebarLink',
  '--wcfHeaderBackground', '--wcfHeaderText', '--wcfHeaderMenuBackground', '--wcfFooterBoxBackground', '--wcfFooterBoxText',
  '--wcfFooterBoxHeadlineText', '--wcfFooterBackground', '--wcfFooterText', '--wcfFontFamily', '--wcfFontSizeDefault',
  '--wcfFontSizeSmall', '--wcfFontSizeHeadline', '--wcfFontSizeSection', '--wcfFontSizeTitle'];

const measure = `(() => {
  const skip = ['none', 'normal', 'auto', 'rgba(0, 0, 0, 0)', '0px'];
  const parts = {};
  for (const [name, selector] of Object.entries(${JSON.stringify(PARTS)})) {
    const el = document.querySelector(selector);
    if (!el) { parts[name] = null; continue; }
    const cs = getComputedStyle(el);
    const r = el.getBoundingClientRect();
    const out = { class: el.className || el.tagName.toLowerCase(), rect: Math.round(r.x) + ',' + Math.round(r.y) + ' ' + Math.round(r.width) + 'x' + Math.round(r.height) };
    for (const p of ${JSON.stringify(PROPS)}) {
      const v = cs.getPropertyValue(p);
      if (v && !skip.includes(v)) out[p] = v;
    }
    const after = getComputedStyle(el, '::after').content;
    if (after && after !== 'none' && after !== 'normal') out['::after'] = after;
    parts[name] = out;
  }
  const root = getComputedStyle(document.documentElement);
  const variables = Object.fromEntries(${JSON.stringify(VARIABLES)}.map((v) => [v, root.getPropertyValue(v).trim()]).filter(([, v]) => v));
  return { variables, parts };
})()`;

const browser = await launchBrowser({ width: 1400, height: 1000 }).catch((error) => {
  console.error(error.message);
  process.exit(1);
});
try {
  await browser.send('Page.navigate', { url });
  await sleep(Number(options.wait));
  const result = { url, viewport: '1400x1000', html: await browser.evaluate(
    `[...document.documentElement.attributes].map((a) => a.name + '=' + a.value).join(' ')`) };
  // WSC switches the color scheme with <html data-color-scheme="light|dark">.
  for (const scheme of ['light', 'dark']) {
    await browser.evaluate(`document.documentElement.dataset.colorScheme = '${scheme}'`);
    await sleep(300);
    result[scheme] = await browser.evaluate(measure);
  }
  const json = JSON.stringify(result, null, 1);
  if (options.out) {
    writeFileSync(options.out, json + '\n');
    console.log(`saved ${options.out}`);
  } else {
    console.log(json);
  }
} finally {
  await browser.close();
}
