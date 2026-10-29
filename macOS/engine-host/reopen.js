'use strict';

const path = require('path');
const { createFocusGate } = require('../deep-link');
const { MAX_FOLDERS, BATCH_MS } = require('../finder-drop');

const OPEN = '/usr/bin/open';

function createReopenRouter({ execFile, bundlePath, log = () => {}, now = Date.now, setTimer = setTimeout }) {
  const reopenGate = createFocusGate({ now });
  const linkGate = createFocusGate({ now });
  let batch = [];
  let timer = null;
  const launch = (targets = null) => {
    if (!bundlePath) {
      log('[engine-service] reopen ignored: no bundle path (dev run)');
      return false;
    }
    const list = targets === null ? [] : [].concat(targets);
    log('[engine-service] reopen: launching a window instance');
    execFile(OPEN, list.length ? ['-n', '-a', bundlePath, ...list] : ['-n', bundlePath], (err) => {
      if (err) log(`[engine-service] could not launch a window instance: ${err.message}`);
    });
    return true;
  };
  const flush = () => {
    timer = null;
    const paths = batch.slice(0, MAX_FOLDERS);
    batch = [];
    return paths.length ? launch(paths) : false;
  };
  return {
    launch,
    flush,
    onReopen: () => (reopenGate.allow() ? launch() : false),
    onOpenFile: (file) => {
      if (typeof file !== 'string' || !path.isAbsolute(file)) return false;
      if (!bundlePath) return launch(file);
      if (batch.length < MAX_FOLDERS && !batch.includes(file)) batch.push(file);
      if (timer === null) timer = setTimer(flush, BATCH_MS);
      return true;
    },
    onOpenUrl: (url) => (typeof url === 'string' && url.startsWith('carnivore:') && linkGate.allow() ? launch(url) : false),
  };
}

function wireReopen({ app, router }) {
  app.on('activate', () => router.onReopen());
  app.on('open-file', (event, file) => { event.preventDefault(); router.onOpenFile(file); });
  app.on('open-url', (event, url) => { event.preventDefault(); router.onOpenUrl(url); });
}

module.exports = { OPEN, createReopenRouter, wireReopen };
