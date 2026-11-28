'use strict';


const crypto = require('crypto');
const fs = require('fs');
const http = require('http');
const https = require('https');
const path = require('path');
const { execFile } = require('child_process');

const VERSION = '2026.10.0';
const BASE_URL = `https://github.com/cloudflare/cloudflared/releases/download/${VERSION}`;

const PINS = {
  arm64: {
    url: `${BASE_URL}/cloudflared-darwin-arm64.tgz`,
    archiveSha256: 'a2f79ff7b9420aa537d74af239f376da170bbabeb529aec416002adac6a72e70',
    binarySha256: '72edfd3eea463aef4d5cb89e2e209cecb048cc756c2b01915de2e0ad7cb39830',
  },
  amd64: {
    url: `${BASE_URL}/cloudflared-darwin-amd64.tgz`,
    archiveSha256: '903845b81828c8cb3c5d13d816a2de71c06a3da5785469df8eb0e1b736d92f9f',
    binarySha256: '0560c9ab7281ac3f746055323623ed23bc0405b6dab9400474020cba33a978da',
  },
};

const MAX_ARCHIVE_BYTES = 100 * 1024 * 1024;
const MAX_REDIRECTS = 10;
const DOWNLOAD_TIMEOUT_MS = 120000;

function sha256OfFile(file) {
  return crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex');
}

function downloadFile(url, dest, redirectsLeft = MAX_REDIRECTS, deadline = Date.now() + DOWNLOAD_TIMEOUT_MS) {
  return new Promise((resolve, reject) => {
    let parsed;
    try {
      parsed = new URL(url);
    } catch (err) {
      reject(err);
      return;
    }
    if (parsed.protocol !== 'https:' && parsed.protocol !== 'http:') {
      reject(new Error(`unsupported download protocol: ${parsed.protocol}`));
      return;
    }
    const remaining = deadline - Date.now();
    if (remaining <= 0) {
      reject(new Error(`download timed out after ${DOWNLOAD_TIMEOUT_MS}ms`));
      return;
    }
    const client = parsed.protocol === 'https:' ? https : http;
    let settled = false;
    let writer = null;
    const fail = (err) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      if (writer) writer.destroy();
      reject(err);
    };
    const req = client.get(parsed, { headers: { 'User-Agent': 'Carnivore' } }, (res) => {
      const status = res.statusCode || 0;
      if (status >= 300 && status < 400 && res.headers.location) {
        res.resume();
        if (redirectsLeft <= 0) {
          fail(new Error('too many redirects'));
          return;
        }
        clearTimeout(timer);
        settled = true;
        const nextUrl = new URL(res.headers.location, parsed).toString();
        downloadFile(nextUrl, dest, redirectsLeft - 1, deadline).then(resolve, reject);
        return;
      }
      if (status < 200 || status >= 300) {
        res.resume();
        fail(new Error(`download failed with HTTP ${status}`));
        return;
      }
      const declaredLen = Number(res.headers['content-length']);
      if (Number.isFinite(declaredLen) && declaredLen > MAX_ARCHIVE_BYTES) {
        res.destroy();
        fail(new Error(`archive exceeds maximum size (${declaredLen} > ${MAX_ARCHIVE_BYTES})`));
        return;
      }
      let received = 0;
      writer = fs.createWriteStream(dest);
      res.on('data', (chunk) => {
        received += chunk.length;
        if (received > MAX_ARCHIVE_BYTES) {
          const err = new Error(`archive exceeds maximum size (${MAX_ARCHIVE_BYTES})`);
          res.destroy(err);
          fail(err);
        }
      });
      res.on('error', fail);
      writer.on('error', fail);
      writer.on('finish', () => {
        if (settled) return;
        settled = true;
        clearTimeout(timer);
        resolve();
      });
      res.pipe(writer);
    });
    const timer = setTimeout(() => {
      const err = new Error(`download timed out after ${DOWNLOAD_TIMEOUT_MS}ms`);
      req.destroy(err);
      fail(err);
    }, remaining);
    if (timer.unref) timer.unref();
    req.on('error', fail);
  });
}

function extractTgz(tgz, outDir) {
  return new Promise((resolve, reject) => {
    execFile('/usr/bin/tar', ['-xzf', tgz, '-C', outDir], (err) => (err ? reject(err) : resolve()));
  });
}

async function ensureVerified({ binDir, arch, pins = PINS, download = downloadFile, extract = extractTgz, verifyOnly = false }) {
  const pin = pins[arch];
  if (!pin) throw new Error(`no cloudflared pin for architecture ${arch}`);
  const target = path.join(binDir, 'cloudflared');
  if (verifyOnly) {
    if (!fs.existsSync(target)) throw new Error('no cloudflared in bin/');
    const got = sha256OfFile(target);
    if (got !== pin.binarySha256) throw new Error(`cloudflared in bin/ does not match the pin (sha256 ${got}); kept, not used`);
    fs.chmodSync(target, 0o755);
    return target;
  }
  fs.mkdirSync(binDir, { recursive: true });

  if (fs.existsSync(target)) {
    if (sha256OfFile(target) === pin.binarySha256) {
      fs.chmodSync(target, 0o755);
      return target;
    }
    fs.rmSync(target, { force: true });
  }

  const work = fs.mkdtempSync(path.join(binDir, '.cloudflared-'));
  try {
    const archive = path.join(work, 'cloudflared.tgz');
    await download(pin.url, archive);
    const archiveHash = sha256OfFile(archive);
    if (archiveHash !== pin.archiveSha256) {
      throw new Error(`cloudflared archive sha256 mismatch (got ${archiveHash}, pinned ${pin.archiveSha256}); refusing to extract`);
    }
    const out = path.join(work, 'out');
    fs.mkdirSync(out);
    await extract(archive, out);
    const extracted = path.join(out, 'cloudflared');
    if (!fs.existsSync(extracted)) throw new Error('cloudflared archive did not contain a cloudflared binary');
    const binaryHash = sha256OfFile(extracted);
    if (binaryHash !== pin.binarySha256) {
      throw new Error(`cloudflared binary sha256 mismatch (got ${binaryHash}, pinned ${pin.binarySha256}); refusing to install`);
    }
    fs.renameSync(extracted, target);
    fs.chmodSync(target, 0o755);
    return target;
  } finally {
    fs.rmSync(work, { recursive: true, force: true });
  }
}

module.exports = { VERSION, PINS, sha256OfFile, ensureVerified, downloadFile, extractTgz };
