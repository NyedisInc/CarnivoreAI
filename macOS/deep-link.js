// start a session

'use strict';

const LINK_MAX = 2048;
const NAME_MAX = 200;
const ASK_ID_PATTERN = /^[A-Za-z0-9_:.-]{1,200}$/;
const SETTINGS_SECTIONS = Object.freeze([
  'account', 'appearance', 'sessions', 'launch_profiles', 'terminal', 'notifications', 'byoai', 'log_processor',
  'remote', 'general', 'desktop', 'keys', 'advanced',
]);
const TAB_PATTERN = /^[a-z_]{1,40}$/;
const LINK_CHARS = /^[\x21-\x7e]+$/;
const PREFIX = /^carnivore:\/\//i;
const LEFTOVER_ESCAPE = /%[0-9a-fA-F]{2}/;
const BAD_NAME_CHARS = /[\x00-\x1f\x7f-\x9f/\\]/;

function refuse(reason) {
  return { ok: false, reason };
}

function decodeName(segment) {
  let name;
  try {
    name = decodeURIComponent(segment);
  } catch (error) {
    return { reason: 'bad percent escape in the name' };
  }
  if (name === '' || name === '.' || name === '..' || BAD_NAME_CHARS.test(name) || name.length > NAME_MAX) {
    return { reason: 'name is empty, a dot segment, too long or carries a control or slash character' };
  }
  if (LEFTOVER_ESCAPE.test(name)) return { reason: 'name is encoded twice' };
  return { name };
}

function segmentsOf(pathname) {
  const path = pathname.endsWith('/') ? pathname.slice(0, -1) : pathname;
  return path === '' ? [] : path.slice(1).split('/');
}

function parseDeepLink(text) {
  if (typeof text !== 'string') return refuse('link is not a string');
  if (text === '') return refuse('link is empty');
  if (text.length > LINK_MAX) return refuse(`link is too long (over ${LINK_MAX} characters)`);
  if (!LINK_CHARS.test(text)) return refuse('link has a character outside printable ascii');
  if (!PREFIX.test(text)) return refuse('wrong scheme: not carnivore://');
  if (text.includes('?')) return refuse('query is not allowed');
  if (text.includes('#')) return refuse('fragment is not allowed');
  const rest = text.slice('carnivore://'.length);
  const slash = rest.indexOf('/');
  const host = slash === -1 ? rest : rest.slice(0, slash);
  if (host.includes('@')) return refuse('userinfo is not allowed');
  if (host.includes(':')) return refuse('port is not allowed');
  const verb = host.toLowerCase();
  const segments = segmentsOf(slash === -1 ? '' : rest.slice(slash));

  switch (verb) {
    case 'open':
      return segments.length === 0 ? { ok: true, kind: 'open', hash: '' } : refuse('open takes no path');
    case 'session':
    case 'project': {
      if (segments.length !== 1) return refuse(segments.length === 0 ? 'name is missing' : 'more than one path segment');
      const decoded = decodeName(segments[0]);
      if (decoded.reason) return refuse(decoded.reason);
      return { ok: true, kind: verb, hash: `session/${encodeURIComponent(decoded.name)}` };
    }
    case 'approvals': {
      if (segments.length !== 1) return refuse(segments.length === 0 ? 'id is missing' : 'more than one path segment');
      const decoded = decodeName(segments[0]);
      if (decoded.reason || !ASK_ID_PATTERN.test(decoded.name)) return refuse('id does not match the ask id pattern');
      return { ok: true, kind: 'approvals', approvalId: decoded.name };
    }
    case 'settings': {
      if (segments.length > 2) return refuse('more than section and tab in the path');
      const [section, tab] = segments;
      if (section !== undefined && !SETTINGS_SECTIONS.includes(section)) return refuse('unknown settings section');
      if (tab !== undefined && !TAB_PATTERN.test(tab)) return refuse('settings tab is not lowercase letters and underscores');
      return { ok: true, kind: 'settings', hash: ['#settings', ...segments].join('/') };
    }
    default:
      return refuse('unknown verb');
  }
}

function findLinkInArgv(argv) {
  if (!Array.isArray(argv)) return null;
  const hit = argv.find((arg) => typeof arg === 'string' && /^carnivore:/i.test(arg));
  return hit === undefined ? null : hit;
}

function createFocusGate({ now, windowMs = 500 }) {
  let last = null;
  return {
    allow() {
      const at = now();
      if (last !== null && at >= last && at - last < windowMs) return false;
      last = at;
      return true;
    },
  };
}

module.exports = { LINK_MAX, SETTINGS_SECTIONS, parseDeepLink, findLinkInArgv, createFocusGate };
