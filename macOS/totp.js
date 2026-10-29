
const crypto = require('crypto');

function base32decode(input) {
  const alpha = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ234567';
  const clean = String(input).toUpperCase().replace(/=+$/, '').replace(/\s+/g, '');
  let bits = '';
  for (const ch of clean) {
    const v = alpha.indexOf(ch);
    if (v < 0) throw new Error(`Invalid base32 char: ${ch}`);
    bits += v.toString(2).padStart(5, '0');
  }
  const bytes = [];
  for (let i = 0; i + 8 <= bits.length; i += 8) {
    bytes.push(parseInt(bits.slice(i, i + 8), 2));
  }
  return Buffer.from(bytes);
}

function currentTotp(secretBase32, step = 30, digits = 6, nowMs = Date.now()) {
  const key = base32decode(secretBase32);
  const counter = Math.floor(nowMs / 1000 / step);
  const buf = Buffer.alloc(8);
  buf.writeBigUInt64BE(BigInt(counter), 0);
  const hmac = crypto.createHmac('sha1', key).update(buf).digest();
  const offset = hmac[hmac.length - 1] & 0xf;
  const code = ((hmac[offset]     & 0x7f) << 24)
             | ((hmac[offset + 1] & 0xff) << 16)
             | ((hmac[offset + 2] & 0xff) <<  8)
             | ( hmac[offset + 3] & 0xff);
  return String(code % (10 ** digits)).padStart(digits, '0');
}

function secondsUntilRollover(step = 30, nowMs = Date.now()) {
  const secs = Math.floor(nowMs / 1000);
  return step - (secs % step);
}

module.exports = { base32decode, currentTotp, secondsUntilRollover };
