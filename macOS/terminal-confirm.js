// the exact argv, one element per line

'use strict';

const crypto = require('crypto');
const fs = require('fs');
const path = require('path');

const CONFIRMED_FILE = 'terminal-custom-confirmed.json';
const EDITOR_CONFIRMED_FILE = 'editor-command-confirmed.json';

function confirmationHash(parts) {
  return crypto.createHash('sha256').update(JSON.stringify(parts)).digest('hex');
}

function storedHash(deps) {
  const io = deps.fs || fs;
  try {
    const stored = JSON.parse(io.readFileSync(path.join(deps.dir, deps.file || CONFIRMED_FILE), 'utf8'));
    return stored && typeof stored.hash === 'string' ? stored.hash : null;
  } catch (error) {
    if (error.code !== 'ENOENT') console.warn('[terminal-confirm] could not read the stored approval; asking again:', error.message);
    return null;
  }
}

function isConfirmed(hash, deps) {
  return storedHash(deps) === hash;
}

function rememberConfirmed(hash, deps) {
  const io = deps.fs || fs;
  const target = path.join(deps.dir, deps.file || CONFIRMED_FILE);
  const temp = `${target}.${process.pid}.tmp`;
  io.writeFileSync(temp, JSON.stringify({ hash }), { mode: 0o600 });
  io.renameSync(temp, target);
}

async function confirmCustom(spec) {
  const hash = confirmationHash(spec.hashParts);
  const earlier = storedHash(spec);
  if (earlier === hash) return true;
  const title = spec.t(spec.titleKey || 'menubar.terminal.confirm_title');
  const lead = earlier ? `${spec.t('menubar.terminal.confirm_changed')}\n\n` : '';
  const answer = await spec.dialog.showMessageBox({
    type: 'warning',
    title,
    message: title,
    detail: `${lead}${spec.t(spec.bodyKey || 'menubar.terminal.confirm_body')}\n\n${spec.argv.map((part) => JSON.stringify(part)).join('\n')}`,
    buttons: [spec.t('menubar.terminal.confirm_run'), spec.t('menubar.terminal.confirm_cancel')],
    defaultId: 1,
    cancelId: 1,
    noLink: true,
  });
  if (!answer || answer.response !== 0) return false;
  rememberConfirmed(hash, spec);
  return true;
}

module.exports = { CONFIRMED_FILE, EDITOR_CONFIRMED_FILE, confirmationHash, storedHash, isConfirmed, rememberConfirmed, confirmCustom };
