
'use strict';

function menuCapabilities(platform, osVersion) {
  if (platform !== 'darwin') return { header: false, sublabel: false, badge: false };
  const [major, minor] = String(osVersion || '').split('.').map((n) => parseInt(n, 10) || 0);
  const atLeast = (a, b) => major > a || (major === a && minor >= b);
  return { header: atLeast(14, 0), sublabel: atLeast(14, 4), badge: atLeast(14, 0) };
}

function degradeItems(items, caps) {
  const out = [];
  for (const source of items) {
    const item = { ...source };
    if (item.submenu) item.submenu = degradeItems(item.submenu, caps);
    if (!caps.badge) delete item.badge;
    const isHeader = item.type === 'header';
    if (isHeader && !caps.header) {
      item.type = 'normal';
      item.enabled = false;
    }
    if (item.sublabel && !caps.sublabel) {
      const sub = item.sublabel;
      delete item.sublabel;
      if (isHeader) {
        out.push(item, { type: 'normal', id: `${item.id || 'header'}.sub`, label: sub, enabled: false });
        continue;
      }
      if (item.enabled === false) item.label = `${item.label} (${sub})`;
      else item.toolTip = item.toolTip || sub;
    }
    out.push(item);
  }
  return out;
}

module.exports = { menuCapabilities, degradeItems };
