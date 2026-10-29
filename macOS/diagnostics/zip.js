
'use strict';

const zlib = require('zlib');

const ZIP_ENTRY_NAMES = Object.freeze(['diagnostics.json', 'crash-events.log', 'crash-dumps.txt', 'README.txt']);
const DOS_DATE = 0x21;

function buildZip(entries, allowed = ZIP_ENTRY_NAMES) {
  const seen = new Set();
  const locals = []; const centrals = []; let offset = 0;
  for (const entry of entries) {
    if (!allowed.includes(entry.name) || seen.has(entry.name)) throw new Error(`zip entry name not allowed: ${entry.name}`);
    seen.add(entry.name);
    const name = Buffer.from(entry.name, 'utf8');
    const raw = Buffer.from(entry.data);
    const deflated = zlib.deflateRawSync(raw);
    const stored = deflated.length >= raw.length;
    const body = stored ? raw : deflated;
    const crc = zlib.crc32(raw);
    const head = Buffer.alloc(30);
    head.writeUInt32LE(0x04034b50, 0); head.writeUInt16LE(20, 4); head.writeUInt16LE(0x0800, 6); head.writeUInt16LE(stored ? 0 : 8, 8);
    head.writeUInt16LE(0, 10); head.writeUInt16LE(DOS_DATE, 12); head.writeUInt32LE(crc, 14);
    head.writeUInt32LE(body.length, 18); head.writeUInt32LE(raw.length, 22); head.writeUInt16LE(name.length, 26); head.writeUInt16LE(0, 28);
    const cen = Buffer.alloc(46);
    cen.writeUInt32LE(0x02014b50, 0); cen.writeUInt16LE(0x031e, 4); cen.writeUInt16LE(20, 6); cen.writeUInt16LE(0x0800, 8);
    cen.writeUInt16LE(stored ? 0 : 8, 10); cen.writeUInt16LE(0, 12); cen.writeUInt16LE(DOS_DATE, 14); cen.writeUInt32LE(crc, 16);
    cen.writeUInt32LE(body.length, 20); cen.writeUInt32LE(raw.length, 24); cen.writeUInt16LE(name.length, 28);
    cen.writeUInt32LE(((0o100600 << 16) >>> 0), 38); cen.writeUInt32LE(offset, 42);
    locals.push(head, name, body); centrals.push(cen, name);
    offset += head.length + name.length + body.length;
  }
  const central = Buffer.concat(centrals);
  const end = Buffer.alloc(22);
  end.writeUInt32LE(0x06054b50, 0); end.writeUInt16LE(entries.length, 8); end.writeUInt16LE(entries.length, 10);
  end.writeUInt32LE(central.length, 12); end.writeUInt32LE(offset, 16);
  return Buffer.concat([...locals, central, end]);
}

module.exports = { ZIP_ENTRY_NAMES, buildZip };
