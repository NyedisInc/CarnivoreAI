
'use strict';

const zlib = require('zlib');
const { SHAPES } = require('./led-hues');

const ICON_POINTS = 14;
const SAMPLES = 4;

const CRC_TABLE = (() => {
  const table = new Uint32Array(256);
  for (let n = 0; n < 256; n += 1) {
    let c = n;
    for (let k = 0; k < 8; k += 1) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    table[n] = c >>> 0;
  }
  return table;
})();

function crc32(buf) {
  let c = 0xffffffff;
  for (let i = 0; i < buf.length; i += 1) c = CRC_TABLE[(c ^ buf[i]) & 0xff] ^ (c >>> 8);
  return (c ^ 0xffffffff) >>> 0;
}

function chunk(type, data) {
  const head = Buffer.alloc(8);
  head.writeUInt32BE(data.length, 0);
  head.write(type, 4, 'ascii');
  const tail = Buffer.alloc(4);
  tail.writeUInt32BE(crc32(Buffer.concat([head.subarray(4), data])), 0);
  return Buffer.concat([head, data, tail]);
}

function encodePng(rgba, width, height) {
  const header = Buffer.alloc(13);
  header.writeUInt32BE(width, 0);
  header.writeUInt32BE(height, 4);
  header[8] = 8;
  header[9] = 6;
  const stride = width * 4;
  const raw = Buffer.alloc((stride + 1) * height);
  for (let y = 0; y < height; y += 1) {
    raw[y * (stride + 1)] = 0;
    Buffer.from(rgba.buffer, rgba.byteOffset + y * stride, stride).copy(raw, y * (stride + 1) + 1);
  }
  return Buffer.concat([Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]), chunk('IHDR', header),
    chunk('IDAT', zlib.deflateSync(raw)), chunk('IEND', Buffer.alloc(0))]);
}

function rgbOf(hex) {
  const n = parseInt(hex.slice(1), 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}

function inCircle(x, y, cx, cy, r) {
  return (x - cx) ** 2 + (y - cy) ** 2 <= r * r;
}

const MID = ICON_POINTS / 2;

function layerAt(shape, x, y) {
  switch (shape) {
    case SHAPES.DISC:
      return inCircle(x, y, MID, MID, 4.6) ? 'main' : null;
    case SHAPES.RING:
      return inCircle(x, y, MID, MID, 4.6) && !inCircle(x, y, MID, MID, 2.9) ? 'main' : null;
    case SHAPES.RING_DOT:
      if (inCircle(x, y, MID, MID, 1.7)) return 'center';
      return inCircle(x, y, MID, MID, 4.6) && !inCircle(x, y, MID, MID, 3.3) ? 'main' : null;
    case SHAPES.MOON:
      return inCircle(x, y, MID, MID, 5) && !inCircle(x, y, MID + 2.4, MID - 1.9, 4.2) ? 'main' : null;
    case SHAPES.SKULL: {
      const head = inCircle(x, y, MID, 6, 4.8) || (x >= 5 && x <= 9 && y >= 8 && y <= 11.6);
      const eye = inCircle(x, y, 5.3, 6.4, 1.3) || inCircle(x, y, 8.7, 6.4, 1.3);
      return head && !eye ? 'main' : null;
    }
    default:
      return null;
  }
}

function renderGlyphPng(glyph, scale) {
  const size = ICON_POINTS * scale;
  const rgba = new Uint8Array(size * size * 4);
  const main = rgbOf(glyph.color);
  const center = rgbOf(glyph.centerColor || glyph.color);
  const total = SAMPLES * SAMPLES;
  for (let py = 0; py < size; py += 1) {
    for (let px = 0; px < size; px += 1) {
      let mainHits = 0;
      let centerHits = 0;
      for (let sy = 0; sy < SAMPLES; sy += 1) {
        for (let sx = 0; sx < SAMPLES; sx += 1) {
          const layer = layerAt(glyph.shape, (px + (sx + 0.5) / SAMPLES) / scale, (py + (sy + 0.5) / SAMPLES) / scale);
          if (layer === 'main') mainHits += 1;
          else if (layer === 'center') centerHits += 1;
        }
      }
      const hits = mainHits + centerHits;
      if (hits === 0) continue;
      const rgb = centerHits > mainHits ? center : main;
      const at = (py * size + px) * 4;
      rgba[at] = rgb[0];
      rgba[at + 1] = rgb[1];
      rgba[at + 2] = rgb[2];
      rgba[at + 3] = Math.round((hits / total) * 255);
    }
  }
  return encodePng(rgba, size, size);
}

module.exports = { ICON_POINTS, renderGlyphPng, encodePng, layerAt };
