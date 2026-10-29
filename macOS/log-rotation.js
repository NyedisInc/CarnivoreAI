/* with a plain */

'use strict';

const fs = require('fs');

const DEFAULT_MAX_BYTES = 50 * 1024 * 1024;
const LOG_FILE_MODE = 0o600;
const DEFAULT_BACKUP_COUNT = 5;

function currentSize(filePath) {
  try {
    return fs.statSync(filePath).size;
  } catch (err) {
    return 0;
  }
}

function openPrivateAppend(filePath) {
  const fd = fs.openSync(filePath, 'a', LOG_FILE_MODE);
  try {
    fs.fchmodSync(fd, LOG_FILE_MODE);
  } catch (err) {
    console.warn(`[log-rotation] could not set ${filePath} to 0600: ${err.code || err.message}`);
  }
  return fd;
}

function rotate(filePath, backupCount) {
  if (backupCount > 0) {
    for (let i = backupCount - 1; i >= 1; i -= 1) {
      const src = `${filePath}.${i}`;
      const dst = `${filePath}.${i + 1}`;
      if (fs.existsSync(src)) {
        fs.renameSync(src, dst);
      }
    }
    if (fs.existsSync(filePath)) {
      fs.renameSync(filePath, `${filePath}.1`);
    }
  } else if (fs.existsSync(filePath)) {
    fs.unlinkSync(filePath);
  }
}

class RotatingLogWriter {
  constructor(filePath, options = {}) {
    this.filePath = filePath;
    this.maxBytes = options.maxBytes || DEFAULT_MAX_BYTES;
    this.backupCount = options.backupCount != null ? options.backupCount : DEFAULT_BACKUP_COUNT;
    this._fd = openPrivateAppend(this.filePath);
    this._size = currentSize(this.filePath);
    this._closed = false;
  }

  write(chunk) {
    if (this._closed || chunk == null || chunk.length === 0) return;
    const buf = Buffer.isBuffer(chunk) ? chunk : Buffer.from(String(chunk), 'utf8');
    try {
      if (this._size > 0 && this._size + buf.length > this.maxBytes) this._rotateNow();
      fs.writeSync(this._fd, buf);
      this._size += buf.length;
    } catch (err) {
      console.warn(`[log-rotation] could not write ${this.filePath}: ${err.code || err.message}`);
    }
  }

  _rotateNow() {
    try {
      fs.closeSync(this._fd);
    } catch (err) {
    }
    try {
      rotate(this.filePath, this.backupCount);
      this._size = 0;
    } catch (err) {
      console.warn(`[log-rotation] could not rotate ${this.filePath}: ${err.code || err.message}`);
    }
    this._fd = openPrivateAppend(this.filePath);
    if (this._size === 0) this._size = currentSize(this.filePath);
  }

  end(finalChunk) {
    if (this._closed) return;
    if (finalChunk) this.write(finalChunk);
    try {
      fs.closeSync(this._fd);
    } catch (err) {
    }
    this._closed = true;
  }
}

function appendWithRotation(filePath, text, options = {}) {
  const maxBytes = options.maxBytes || DEFAULT_MAX_BYTES;
  const backupCount = options.backupCount != null ? options.backupCount : DEFAULT_BACKUP_COUNT;
  const buf = Buffer.from(String(text), 'utf8');
  try {
    const size = currentSize(filePath);
    if (size > 0 && size + buf.length > maxBytes) {
      rotate(filePath, backupCount);
    }
    const fd = openPrivateAppend(filePath);
    try {
      fs.writeSync(fd, buf);
    } finally {
      fs.closeSync(fd);
    }
  } catch (err) {
    console.warn(`[log-rotation] could not append to ${filePath}: ${err.code || err.message}`);
  }
}

module.exports = {
  RotatingLogWriter,
  appendWithRotation,
  openPrivateAppend,
  rotate,
  DEFAULT_MAX_BYTES,
  DEFAULT_BACKUP_COUNT,
  LOG_FILE_MODE,
};
