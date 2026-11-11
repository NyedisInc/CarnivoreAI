
'use strict';

const fs = require('fs');
const os = require('os');
const path = require('path');
const crypto = require('crypto');

const MEDIA_BASE = '/api/v1/notifications/media/';
const MEDIA_ID = /^[0-9a-f]{32}$/;
const MAX_WIDTH = 720;
const MAX_BYTES = 12 * 1024 * 1024;
const MAX_AGE_MS = 7 * 24 * 60 * 60 * 1000;
const FOLDER = 'carnivore-notify-thumbs';

function pictureRoute(kind, media, hasPoster) {
  const id = media && typeof media.id === 'string' ? media.id : '';
  if (!MEDIA_ID.test(id)) return '';
  if (kind === 'image') return MEDIA_BASE + id;
  if (kind === 'video' || (kind === 'file' && hasPoster === true)) return `${MEDIA_BASE}${id}/poster`;
  return '';
}

async function fetchBytes(api, route) {
  const doFetch = api.fetchImpl || global.fetch;
  for (let attempt = 0; attempt < 2; attempt += 1) {
    const { token } = await api.ensureToken();
    if (!token) return null;
    const response = await doFetch(api.baseUrl + route, { headers: { Authorization: `Bearer ${token}` }, signal: AbortSignal.timeout(8000) });
    if (response.status === 401 && attempt === 0) { api.forgetToken(); continue; }
    if (!response.ok) return null;
    const length = Number(response.headers.get('content-length'));
    if (Number.isFinite(length) && length > MAX_BYTES) return null;
    const bytes = Buffer.from(await response.arrayBuffer());
    return bytes.length > 0 && bytes.length <= MAX_BYTES ? bytes : null;
  }
  return null;
}

function createThumbnails(deps) {
  const dir = deps.dir || path.join(os.tmpdir(), FOLDER);
  const now = deps.now || Date.now;
  const fileOf = (toastId) => path.join(dir, `${crypto.createHash('sha256').update(String(toastId)).digest('hex').slice(0, 32)}.png`);

  function prune() {
    let names = [];
    try { names = fs.readdirSync(dir); } catch (error) { return; }
    for (const name of names) {
      const file = path.join(dir, name);
      try {
        if (now() - fs.statSync(file).mtimeMs > MAX_AGE_MS) fs.unlinkSync(file);
      } catch (error) {
        console.warn('[thumbnail] could not prune a cached picture:', String((error && error.code) || error));
      }
    }
  }

  function release(toastId) {
    try { fs.unlinkSync(fileOf(toastId)); } catch (error) {  }
  }

  async function get(api, toastId, kind, response) {
    const route = pictureRoute(kind, response.media, !!(response.card && response.card.poster));
    if (!route) return null;
    try {
      const bytes = await fetchBytes(api, route);
      if (!bytes) return null;
      let image = deps.nativeImage.createFromBuffer(bytes);
      if (image.isEmpty()) return null;
      const { width } = image.getSize();
      if (width > MAX_WIDTH) image = image.resize({ width: MAX_WIDTH, quality: 'good' });
      const png = image.toPNG();
      fs.mkdirSync(dir, { recursive: true, mode: 0o700 });
      fs.chmodSync(dir, 0o700);
      prune();
      const file = fileOf(toastId);
      fs.writeFileSync(file, png, { mode: 0o600 });
      fs.chmodSync(file, 0o600);
      return { file, dataUrl: `data:image/png;base64,${png.toString('base64')}` };
    } catch (error) {
      console.warn('[thumbnail] no picture for this banner:', String((error && error.message) || error));
      return null;
    }
  }

  return { get, release, prune };
}

module.exports = { MEDIA_BASE, MAX_AGE_MS, pictureRoute, createThumbnails };
