// WHY THIS FILE EXISTS

'use strict';

const os = require('os');

const LINK_LOCAL_V4_PREFIX = '169.254.';

function isBindableAddress(addr) {
  if (!addr) return false;
  const isV4 = addr.family === 'IPv4' || addr.family === 4;
  if (!isV4) return false;
  if (addr.internal) return false;
  if (typeof addr.address !== 'string') return false;
  if (addr.address.startsWith(LINK_LOCAL_V4_PREFIX)) return false;
  return true;
}

function listBindableIps(interfaces) {
  const source = interfaces || os.networkInterfaces() || {};
  const results = [];

  for (const [name, addrs] of Object.entries(source)) {
    if (!Array.isArray(addrs)) continue;
    for (const addr of addrs) {
      if (!isBindableAddress(addr)) continue;
      results.push({ iface: name, ip: addr.address });
    }
  }

  results.sort((a, b) => a.iface.localeCompare(b.iface));
  return results;
}

function isTailscaleIp(ip) {
  const parts = String(ip).split('.');
  if (parts.length !== 4) return false;
  const first = Number(parts[0]);
  const second = Number(parts[1]);
  if (!Number.isInteger(first) || !Number.isInteger(second)) return false;
  return first === 100 && second >= 64 && second <= 127;
}

module.exports = {
  LINK_LOCAL_V4_PREFIX,
  isBindableAddress,
  listBindableIps,
  isTailscaleIp,
};
