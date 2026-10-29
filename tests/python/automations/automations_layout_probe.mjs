import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import { createRequire } from 'node:module';

const [pwDir, clientDir, theme, widthList, shotDir, closedToo] = process.argv.slice(2);
const { chromium } = createRequire(import.meta.url)(pwDir);

const RAIL = 28;
const ZONE = 460;
const TYPES = { '.html': 'text/html', '.js': 'text/javascript', '.mjs': 'text/javascript', '.css': 'text/css', '.json': 'application/json', '.svg': 'image/svg+xml', '.png': 'image/png', '.woff2': 'font/woff2' };

function themeList() {
  const dir = path.join(clientDir, 'css', 'themes');
  return JSON.stringify(fs.readdirSync(dir).filter((d) => fs.existsSync(path.join(dir, d, 'theme.json')))
    .map((d) => ({ ...JSON.parse(fs.readFileSync(path.join(dir, d, 'theme.json'), 'utf8')), source: 'builtin' })));
}

const server = http.createServer((req, res) => {
  const clean = decodeURIComponent((req.url ?? '').split('?')[0].split('#')[0]);
  if (clean === '/api/v1/themes') { res.writeHead(200, { 'content-type': 'application/json' }); res.end(themeList()); return; }
  const file = clean.startsWith('/static/') ? path.join(clientDir, clean.slice('/static/'.length)) : '';
  if (!file || !file.startsWith(clientDir) || !fs.existsSync(file) || fs.statSync(file).isDirectory()) { res.writeHead(404); res.end(); return; }
  res.writeHead(200, { 'content-type': TYPES[path.extname(file)] ?? 'application/octet-stream', 'cache-control': 'no-store' });
  fs.createReadStream(file).pipe(res);
});
await new Promise((ok) => server.listen(0, '127.0.0.1', ok));
const base = `http://127.0.0.1:${server.address().port}`;

const browser = await chromium.launch();
const results = [];
try {
  for (const width of widthList.split(',').map(Number)) {
    const page = await browser.newPage({ viewport: { width: RAIL + width + ZONE, height: 900 } });
    await page.goto(`${base}/static/style-guide.html${theme === 'carnivore' ? '' : `?theme=${theme}`}`, { waitUntil: 'load' });
    await page.waitForSelector("html[data-sg-mounted='true']", { state: 'attached', timeout: 20000 });
    await page.waitForSelector('#sg-live-automations-page .ap-pn[data-open]', { state: 'attached', timeout: 20000 });
    await page.evaluate(({ rail, w }) => {
      const box = document.querySelector('.sg-automations-demo');
      box.setAttribute('style', `position: fixed; left: ${rail}px; top: 0; bottom: 0; width: ${w}px; height: auto; transform: none; zoom: 1; overflow: hidden; z-index: 10000; display: grid`);
      box.removeAttribute('inert');
      box.closest('[inert]')?.removeAttribute('inert');
      window.scrollTo(0, 0);
    }, { rail: RAIL, w: width });
    await page.evaluate(() => document.querySelector('.sg-automations-demo [role="tab"][data-tab="advanced"]').click());
    await page.waitForSelector('.sg-automations-demo [data-scheduled-tree]', { state: 'attached', timeout: 20000 });
    await page.waitForSelector('.sg-automations-demo .ap-pn[data-open]', { state: 'attached', timeout: 20000 });
    await page.waitForTimeout(400);
    const m = await page.evaluate(() => {
      const r = (sel) => { const el = document.querySelector(`.sg-automations-demo ${sel}`); if (!el) return null; const b = el.getBoundingClientRect(); return { left: b.left, right: b.right, top: b.top, bottom: b.bottom, width: b.width, height: b.height }; };
      return { page: r('.ap-page'), list: r('.ap-listcol'), pane: r('.ap-pn'), never: r('[data-pane-never-ran]'), tree: r('[data-scheduled-tree]'), treeName: r('.ap-st-name'), title: r('.oc-titlebar'), toolbar: r('.ap-lt') };
    });
    results.push({ width, ...m });
    const clip = { x: 0, y: 0, width: RAIL + width + ZONE, height: 900 };
    if (shotDir && shotDir !== '-') await page.screenshot({ path: path.join(shotDir, `automations-${width}-${theme}.png`), clip });
    if (shotDir && shotDir !== '-' && closedToo === 'closed') {
      await page.click('.sg-automations-demo .ap-pn-close');
      await page.waitForTimeout(400);
      await page.screenshot({ path: path.join(shotDir, `automations-${width}-${theme}-pane-closed.png`), clip });
    }
    await page.close();
  }
} finally {
  await browser.close();
  server.close();
}
process.stdout.write(`${JSON.stringify({ theme, results })}\n`);
