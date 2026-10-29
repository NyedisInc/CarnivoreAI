
'use strict';

function sep() {
  return { type: 'separator' };
}

function act(id, label, action, extra) {
  return { type: 'normal', id, label, enabled: true, action, ...(extra || {}) };
}

function off(id, label, reason) {
  const item = { type: 'normal', id, label, enabled: false };
  if (reason) item.sublabel = reason;
  return item;
}

function maybe(enabled, id, label, action, reason, extra) {
  return enabled ? act(id, label, action, extra) : off(id, label, reason);
}

function sub(id, label, submenu, extra) {
  return { type: 'submenu', id, label, enabled: true, submenu, ...(extra || {}) };
}

function check(id, label, checked, action, extra) {
  return { type: 'checkbox', id, label, enabled: true, checked: Boolean(checked), action, ...(extra || {}) };
}

function radio(id, label, checked, action, extra) {
  return { type: 'radio', id, label, enabled: true, checked: Boolean(checked), action, ...(extra || {}) };
}

function tidy(items) {
  const out = [];
  for (const item of items) {
    if (!item) continue;
    if (item.type === 'separator' && (out.length === 0 || out[out.length - 1].type === 'separator')) continue;
    out.push(item);
  }
  while (out.length && out[out.length - 1].type === 'separator') out.pop();
  return out;
}

module.exports = { sep, act, off, maybe, sub, check, radio, tidy };
