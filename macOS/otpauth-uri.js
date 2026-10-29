
'use strict';

const ISSUER = 'Carnivore';
const FALLBACK_ACCOUNT = 'carnivore';
const MAX_ACCOUNT_CODE_POINTS = 64;

const DROP_RANGES = Object.freeze([
  [0x0000, 0x001f], [0x007f, 0x009f], [0x00ad, 0x00ad],
  [0x200b, 0x200f], [0x202a, 0x202e], [0x2066, 0x2069],
  [0x2060, 0x2064], [0xfeff, 0xfeff], [0xd800, 0xdfff],
]);

const SPACE_RANGES = Object.freeze([
  [0x0020, 0x0020], [0x00a0, 0x00a0], [0x1680, 0x1680], [0x2000, 0x200a],
  [0x2028, 0x2029], [0x202f, 0x202f], [0x205f, 0x205f], [0x3000, 0x3000],
]);

function inRanges(cp, ranges) {
  return ranges.some(([lo, hi]) => cp >= lo && cp <= hi);
}

function trimTrailingSpace(chars) {
  while (chars.length && chars[chars.length - 1] === ' ') chars.pop();
  return chars;
}

function sanitizeAccount(name) {
  const out = [];
  for (const ch of Array.from(String(name == null ? '' : name))) {
    const cp = ch.codePointAt(0);
    if (inRanges(cp, DROP_RANGES) || ch === ':') continue;
    if (inRanges(cp, SPACE_RANGES)) {
      if (out.length && out[out.length - 1] === ' ') continue;
      out.push(' ');
      continue;
    }
    out.push(ch);
  }
  trimTrailingSpace(out);
  while (out.length && out[0] === ' ') out.shift();
  const cut = trimTrailingSpace(out.slice(0, MAX_ACCOUNT_CODE_POINTS));
  return cut.length ? cut.join('') : FALLBACK_ACCOUNT;
}

function pct(s) {
  return encodeURIComponent(s).replace(
    /[!'()*]/g,
    (c) => '%' + c.charCodeAt(0).toString(16).toUpperCase()
  );
}

function buildOtpauthUri(secret, computerName) {
  const issuer = pct(ISSUER);
  const account = pct(sanitizeAccount(computerName));
  return `otpauth://totp/${issuer}:${account}?secret=${secret}&issuer=${issuer}`;
}

module.exports = { sanitizeAccount, buildOtpauthUri };
