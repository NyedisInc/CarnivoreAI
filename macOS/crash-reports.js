
'use strict';

const path = require('path');

const MAX_DUMPS = 10;
const MAX_DUMP_AGE_MS = 30 * 24 * 3600 * 1000;
const LOG_MAX_BYTES = 256 * 1024;
const LOG_KEEP_BYTES = 128 * 1024;
const FIELDS = Object.freeze(['reason', 'exitCode', 'type', 'serviceName', 'name', 'code']);
const EVENTS = Object.freeze(['render-process-gone', 'child-process-gone', 'uncaught-exception']);
const CRASH_LINE = /^\d{4}-\d\d-\d\dT[\d:.]+Z (render-process-gone|child-process-gone|uncaught-exception)( (reason|exitCode|type|serviceName|name|code)=[A-Za-z0-9_.-]{1,64})*$/;

function formatLine(event, fields, when = new Date()) {
  if (!EVENTS.includes(event)) return null;
  const parts = [when.toISOString(), event];
  for (const key of FIELDS) {
    const value = fields ? fields[key] : undefined;
    if ((typeof value === 'string' || typeof value === 'number') && /^[A-Za-z0-9_.-]{1,64}$/.test(String(value))) parts.push(`${key}=${value}`);
  }
  return parts.join(' ');
}

function listDumps(dir, fs) {
  const out = [];
  const walk = (current) => {
    let entries;
    try { entries = fs.readdirSync(current, { withFileTypes: true }); } catch (_) { return; }
    for (const entry of entries) {
      const file = path.join(current, entry.name);
      if (entry.isDirectory()) walk(file);
      else if (entry.name.endsWith('.dmp')) {
        try { const st = fs.statSync(file); out.push({ file, rel: path.relative(dir, file), size: st.size, mtimeMs: st.mtimeMs }); } catch (_) {  }
      }
    }
  };
  walk(dir);
  return out.sort((a, b) => b.mtimeMs - a.mtimeMs);
}

function sweepDumps(dir, { maxFiles = MAX_DUMPS, maxAgeMs = MAX_DUMP_AGE_MS, fs, now = Date.now() }) {
  const removed = [];
  listDumps(dir, fs).forEach((dump, index) => {
    if (index < maxFiles && now - dump.mtimeMs <= maxAgeMs) return;
    try { fs.unlinkSync(dump.file); removed.push(dump.file); } catch (_) {  }
  });
  return removed;
}

function capLog(file, { fs }) {
  let size;
  try { size = fs.statSync(file).size; } catch (_) { return false; }
  if (size <= LOG_MAX_BYTES) return false;
  const tail = fs.readFileSync(file).subarray(size - LOG_KEEP_BYTES).toString('utf8');
  fs.writeFileSync(file, tail.slice(tail.indexOf('\n') + 1), { mode: 0o600 });
  fs.chmodSync(file, 0o600);
  return true;
}

function start({ app, crashReporter, fs }) {
  const dir = path.join(app.getPath('userData'), 'crash-dumps');
  fs.mkdirSync(dir, { recursive: true, mode: 0o700 });
  fs.chmodSync(dir, 0o700);
  app.setPath('crashDumps', dir);
  sweepDumps(dir, { fs });
  crashReporter.start({ uploadToServer: false, compress: true, ignoreSystemCrashHandler: false });
  return dir;
}

function wire({ app, process: proc, fs, logPath, now = () => new Date(), echo = (line) => console.error(line) }) {
  const record = (event, fields) => {
    const line = formatLine(event, fields, now());
    if (!line) return;
    try {
      fs.mkdirSync(path.dirname(logPath), { recursive: true, mode: 0o700 });
      fs.appendFileSync(logPath, `${line}\n`, { mode: 0o600 });
      fs.chmodSync(logPath, 0o600);
      capLog(logPath, { fs });
    } catch (_) {  }
    echo(`[crash] ${line}`);
  };
  app.on('render-process-gone', (_event, _contents, details) => record('render-process-gone', details || {}));
  app.on('child-process-gone', (_event, details) => record('child-process-gone', details || {}));
  proc.on('uncaughtException', (error) => record('uncaught-exception', { name: error && error.name, code: error && error.code }));
}

module.exports = { MAX_DUMPS, MAX_DUMP_AGE_MS, LOG_MAX_BYTES, CRASH_LINE, formatLine, listDumps, sweepDumps, capLog, start, wire };
