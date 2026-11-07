// Starts a Chromium-based browser (Chrome, Chromium or Edge) without window and controls it via the
// DevTools protocol. No npm packages needed, Node.js >= 22 (built-in WebSocket).
// The browser is found automatically, the environment variable BROWSER overrides it.
import { spawn } from 'node:child_process';
import { existsSync, mkdtempSync, readFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { delimiter, join } from 'node:path';

export const sleep = (ms) => new Promise((ok) => setTimeout(ok, ms));

// Path of the browser: BROWSER or the first installed one of the usual locations.
export function findBrowser() {
  if (process.env.BROWSER) {
    return process.env.BROWSER;
  }
  const candidates = [];
  if (process.platform === 'win32') {
    const bases = [process.env['ProgramFiles(x86)'], process.env.ProgramFiles, process.env.LOCALAPPDATA].filter(Boolean);
    for (const base of bases) {
      candidates.push(
        join(base, 'Microsoft/Edge/Application/msedge.exe'),
        join(base, 'Google/Chrome/Application/chrome.exe'),
        join(base, 'Chromium/Application/chrome.exe'),
      );
    }
  } else if (process.platform === 'darwin') {
    candidates.push(
      '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
      '/Applications/Chromium.app/Contents/MacOS/Chromium',
      '/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge',
    );
  } else {
    const names = ['google-chrome', 'google-chrome-stable', 'chromium', 'chromium-browser', 'microsoft-edge', 'microsoft-edge-stable'];
    for (const dir of (process.env.PATH || '').split(delimiter).filter(Boolean)) {
      candidates.push(...names.map((name) => join(dir, name)));
    }
  }
  return candidates.find((path) => existsSync(path)) ?? null;
}

// Starts the browser with an empty temporary profile and returns helpers to control it.
// width/height = viewport in CSS pixels, scale = device pixel ratio (2 = sharp images).
export async function launchBrowser({ width = 1400, height = 1000, scale = 1 } = {}) {
  const path = findBrowser();
  if (!path) {
    throw new Error('No Chrome, Chromium or Edge found, set the environment variable BROWSER to its path.');
  }
  const profile = mkdtempSync(join(tmpdir(), 'mcstatus-tools-'));
  const args = ['--headless=new', '--remote-debugging-port=0', `--user-data-dir=${profile}`,
    '--no-first-run', '--no-default-browser-check', '--hide-scrollbars', 'about:blank'];
  if (process.getuid?.() === 0) {
    args.unshift('--no-sandbox');  // Chromium refuses to run as root (e.g. in containers) otherwise
  }
  const browser = spawn(path, args, { stdio: 'ignore' });
  let startError = null;
  browser.once('error', (error) => { startError = error; });  // e.g. wrong path in BROWSER
  let ws;
  const cleanup = async () => {
    ws?.close();
    // Wait until the browser has exited (max. 5 s), it still writes into the profile while closing.
    const exited = new Promise((ok) => {
      if (browser.exitCode !== null || browser.signalCode !== null || startError) {
        ok();
      } else {
        browser.once('exit', ok);
        setTimeout(ok, 5000);
      }
    });
    browser.kill();
    await exited;
    try {
      rmSync(profile, { recursive: true, force: true, maxRetries: 10, retryDelay: 200 });
    } catch (error) {
      console.warn(`Could not remove the temporary browser profile ${profile}: ${error.code ?? error.message}`);
    }
  };

  try {
    // The browser writes the chosen debugging port into the profile.
    let target;
    for (let i = 0; i < 100 && !target && !startError; i++) {
      await sleep(100);
      try {
        const port = readFileSync(join(profile, 'DevToolsActivePort'), 'utf8').split('\n')[0];
        target = (await (await fetch(`http://127.0.0.1:${port}/json/list`)).json()).find((t) => t.type === 'page');
      } catch { /* not ready yet */ }
    }
    if (!target) {
      throw new Error(`Browser did not start: ${path}${startError ? ` (${startError.message})` : ''}`);
    }

    ws = new WebSocket(target.webSocketDebuggerUrl);
    await new Promise((ok, fail) => { ws.onopen = ok; ws.onerror = fail; });
    let nextId = 0;
    const pending = new Map();
    ws.onmessage = (event) => {
      const msg = JSON.parse(event.data);
      if (pending.has(msg.id)) {
        pending.get(msg.id)(msg);
        pending.delete(msg.id);
      }
    };

    // DevTools protocol command, see https://chromedevtools.github.io/devtools-protocol/
    const send = (method, params = {}) => new Promise((ok, fail) => {
      const id = ++nextId;
      pending.set(id, (msg) => (msg.error ? fail(new Error(`${method}: ${msg.error.message}`)) : ok(msg.result)));
      ws.send(JSON.stringify({ id, method, params }));
    });
    // Runs JavaScript in the page and returns the (JSON) result, promises are awaited.
    const evaluate = async (expression) => {
      const result = await send('Runtime.evaluate', { expression, awaitPromise: true, returnByValue: true });
      if (result.exceptionDetails) {
        throw new Error(result.exceptionDetails.exception?.description || 'evaluate failed');
      }
      return result.result.value;
    };
    // PNG of a page area in CSS pixels (also outside the viewport).
    const screenshot = async (clip) => Buffer.from((await send('Page.captureScreenshot', {
      format: 'png', captureBeyondViewport: true, clip: { ...clip, scale: 1 },
    })).data, 'base64');

    await send('Page.enable');
    await send('Emulation.setDeviceMetricsOverride', { width, height, deviceScaleFactor: scale, mobile: false });
    return { send, evaluate, screenshot, close: cleanup };
  } catch (error) {
    await cleanup();
    throw error;
  }
}
