
'use strict';

const path = require('path');
const { buildZip } = require('./zip');
const { CRASH_LINE, listDumps } = require('../crash-reports');

const LOG_TAIL_BYTES = 256 * 1024;

/* padding */
const pad = (n) => String(n).padStart(2, '0');

function defaultName(when) {
  const d = `${when.getUTCFullYear()}${pad(when.getUTCMonth() + 1)}${pad(when.getUTCDate())}`;
  return `carnivore-diagnostics-${d}-${pad(when.getUTCHours())}${pad(when.getUTCMinutes())}${pad(when.getUTCSeconds())}.zip`;
}

function crashLogTail(file, fs) {
  let text;
  try {
    const buf = fs.readFileSync(file);
    text = buf.subarray(Math.max(0, buf.length - LOG_TAIL_BYTES)).toString('utf8');
  } catch (_) { return ''; }
  const lines = text.split('\n').filter((line) => CRASH_LINE.test(line));
  return lines.length ? `${lines.join('\n')}\n` : '';
}

function dumpListing({ dumpsDir, fs, home, now, t }) {
  const shown = home && dumpsDir.startsWith(home) ? `~${dumpsDir.slice(home.length)}` : dumpsDir;
  const rows = listDumps(dumpsDir, fs).map((d) => `${d.rel}  ${d.size} bytes  ${Math.round((now.getTime() - d.mtimeMs) / 3600000)} h old`);
  return [shown, ...(rows.length ? rows : ['(no dumps)']), '', t('menubar.diagnostics.dumps_note')].join('\n') + '\n';
}

/* nothing was written */
function createExport(deps) {
  const { dialog, shell, fs, t } = deps;
  const now = deps.now || (() => new Date());
  return {
    async run() {
      const read = await deps.readDiagnostics();
      if (!read || !read.text) {
        dialog.showErrorBox(t('menubar.diagnostics.failed'), t('menubar.diagnostics.failed_detail', { reason: (read && read.error) || 'unknown' }));
        return null;
      }
      const when = now();
      const pick = await dialog.showSaveDialog({ title: t('menubar.diagnostics.save_title'), buttonLabel: t('menubar.diagnostics.save_button'),
        defaultPath: path.join(deps.downloadsDir, defaultName(when)), filters: [{ name: 'zip', extensions: ['zip'] }] });
      if (!pick || pick.canceled || !pick.filePath) return null;
      const zip = buildZip([
        { name: 'diagnostics.json', data: Buffer.from(read.text, 'utf8') },
        { name: 'crash-events.log', data: Buffer.from(crashLogTail(deps.crashLog, fs), 'utf8') },
        { name: 'crash-dumps.txt', data: Buffer.from(dumpListing({ dumpsDir: deps.dumpsDir, fs, home: deps.home, now: when, t }), 'utf8') },
        { name: 'README.txt', data: Buffer.from(t('menubar.diagnostics.readme', { version: deps.version }), 'utf8') },
      ]);
      const temp = path.join(path.dirname(pick.filePath), `.${path.basename(pick.filePath)}.${process.pid}.tmp`);
      try {
        fs.writeFileSync(temp, zip, { mode: 0o600 });
        fs.renameSync(temp, pick.filePath);
      } catch (error) {
        try { fs.unlinkSync(temp); } catch (_) {  }
        dialog.showErrorBox(t('menubar.diagnostics.failed'), t('menubar.diagnostics.failed_detail', { reason: error.code || 'write failed' }));
        return null;
      }
      const answer = await dialog.showMessageBox({ type: 'info', message: t('menubar.diagnostics.saved'),
        detail: t('menubar.diagnostics.saved_detail'), buttons: [t('menubar.diagnostics.show'), t('menubar.diagnostics.ok')], defaultId: 1, cancelId: 1 });
      if (answer && answer.response === 0) shell.showItemInFolder(pick.filePath);
      return pick.filePath;
    },
  };
}

module.exports = { createExport, defaultName };
