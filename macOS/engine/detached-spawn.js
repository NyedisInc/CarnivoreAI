'use strict';

const childProcess = require('node:child_process');
const nodeFs = require('node:fs');
const path = require('node:path');
const { ensureDirMode, PRIVATE_DIR_MODE } = require('./fs-perms');
const { appendWithRotation, openPrivateAppend } = require('../log-rotation');

const ENGINE_ARGS = Object.freeze(['-m', 'src.main']);

function spawnDetachedEngine({
  pythonPath, cwd, env, logFile, banner = '', args = ENGINE_ARGS, maxBytes, backupCount,
  spawnImpl = childProcess.spawn, fsImpl = nodeFs,
}) {
  ensureDirMode(path.dirname(logFile), PRIVATE_DIR_MODE);
  const caps = { maxBytes, backupCount };
  appendWithRotation(logFile, banner, caps);
  const fd = openPrivateAppend(logFile);
  let child;
  try {
    child = spawnImpl(pythonPath, [...args], { cwd, env, detached: true, stdio: ['ignore', fd, fd] });
  } finally {
    fsImpl.closeSync(fd);
  }
  child.unref();
  return { pid: child.pid, child };
}

function appendEngineLog(logFile, text) {
  try {
    appendWithRotation(logFile, text);
  } catch (err) {
    console.warn('Could not write to the server log:', err.message);
  }
}

module.exports = { ENGINE_ARGS, spawnDetachedEngine, appendEngineLog };
