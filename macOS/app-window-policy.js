
'use strict';

const crypto = require('crypto');

const ALLOWED_PERMISSIONS = Object.freeze(['notifications', 'clipboard-sanitized-write']);

function originOf(url) {
  if (typeof url !== 'string') return null;
  let parsed;
  try {
    parsed = new URL(url);
  } catch (_err) {
    return null;
  }
  if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') return null;
  return parsed.origin;
}

function partitionForOrigin(origin) {
  const clean = originOf(origin);
  if (clean === null || clean !== origin) {
    throw new Error(`not an http(s) origin: ${String(origin)}`);
  }
  const hash = crypto.createHash('sha256').update(origin).digest('hex').slice(0, 12);
  return `persist:carnivore-${hash}`;
}

function decideNavigation(targetUrl, appOrigin) {
  const target = originOf(targetUrl);
  if (target === null) return 'deny';
  return target === appOrigin ? 'allow' : 'external';
}

const MAX_POPOUT_SEARCH = 2000;
const POPOUT_PATH = '/static/popout.html';

function soloRowOf(url) {
  if (originOf(url) === null) return null;
  const u = new URL(url);
  if (u.username || u.password || u.pathname !== '/' || u.hash !== '') return null;
  const m = /^\?solo=(\d{1,15})$/.exec(u.search);
  return m ? m[1] : null;
}

function nativeTarget(url, appOrigin) {
  if (originOf(url) !== appOrigin) return null;
  const u = new URL(url);
  if (u.username || u.password) return null;
  const row = soloRowOf(url);
  if (row) return { kind: 'solo', path: `/?solo=${row}` };
  if (u.pathname === POPOUT_PATH && u.search.length <= MAX_POPOUT_SEARCH) return { kind: 'popout', path: u.pathname + u.search };
  return null;
}

/* a fresh nonce name is a second window */
function popoutWindowKey(url, frameName) {
  const row = soloRowOf(url);
  if (row) return `solo:row:${row}`;
  if (typeof frameName === 'string' && /^[\x20-\x7e]{1,160}$/.test(frameName)) return `popout:${frameName}`;
  const u = new URL(url);
  return `popout:${crypto.createHash('sha256').update(u.pathname + u.search).digest('hex').slice(0, 12)}`;
}

function boundsFromFeatures(features) {
  const out = {};
  if (typeof features !== 'string') return out;
  const names = { width: 'width', height: 'height', left: 'x', top: 'y' };
  for (const part of features.split(',')) {
    const [rawKey, rawVal] = part.split('=');
    const key = names[(rawKey || '').trim().toLowerCase()];
    const num = Number.parseInt(rawVal, 10);
    if (key && Number.isFinite(num) && Math.abs(num) <= 20000) out[key] = num;
  }
  return out;
}

function decideWindowOpen(targetUrl, appOrigin, _disposition) {
  const verdict = decideNavigation(targetUrl, appOrigin);
  if (verdict === 'external') return 'external';
  return verdict === 'allow' && nativeTarget(targetUrl, appOrigin) ? 'native' : 'deny';
}

function isPermissionAllowed(permission, requestUrl, appOrigin) {
  return ALLOWED_PERMISSIONS.includes(permission) && originOf(requestUrl) === appOrigin;
}

function isLoopbackOrigin(origin) {
  let url;
  try {
    url = new URL(String(origin));
  } catch (err) {
    return false;
  }
  return (url.protocol === 'http:' || url.protocol === 'https:') &&
    ['127.0.0.1', 'localhost', '[::1]'].includes(url.hostname);
}

module.exports = {
  originOf, isLoopbackOrigin, partitionForOrigin, decideNavigation, decideWindowOpen, isPermissionAllowed, ALLOWED_PERMISSIONS,
  soloRowOf, nativeTarget, popoutWindowKey, boundsFromFeatures,
};
