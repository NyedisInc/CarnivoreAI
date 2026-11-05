#!/usr/bin/env node
'use strict';
const fs = require('fs');
const path = require('path');
const { createRequire } = require('module');

const ROOT = path.join(__dirname, '..', '..');
const { JSDOM } = createRequire(path.join(ROOT, 'web', 'package.json'))('jsdom');
const SOURCE = fs.readFileSync(path.join(ROOT, 'client', 'js', 'modal-ring.js'), 'utf8');

const ROWS = 20000;
const PAGE_SIZE = 2000;

async function run(withRing) {
  const dom = new JSDOM('<!doctype html><body><div id="host"></div></body>', { runScripts: 'outside-only' });
  const { document } = dom.window;
  for (let i = 0; i < PAGE_SIZE; i++) document.body.appendChild(document.createElement('div'));
  if (withRing) dom.window.eval(SOURCE);
  const host = document.getElementById('host');
  const start = process.hrtime.bigint();
  for (let i = 0; i < ROWS; i++) {
    const row = document.createElement('div');
    for (let c = 0; c < 3; c++) row.appendChild(document.createElement('span'));
    host.appendChild(row);
  }
  await new Promise((resolve) => setTimeout(resolve, 0));
  return Number(process.hrtime.bigint() - start) / 1e6;
}

(async () => {
  await run(false);
  const bare = await run(false);
  const ring = await run(true);
  const perRowUs = ((ring - bare) / ROWS) * 1000;
  console.log(`without modal-ring: ${bare.toFixed(1)} ms for ${ROWS} rows`);
  console.log(`with modal-ring:    ${ring.toFixed(1)} ms for ${ROWS} rows`);
  console.log(`observer cost: ${perRowUs.toFixed(2)} us per inserted row (4 elements)`);
})();
