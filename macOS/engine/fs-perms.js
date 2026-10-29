'use strict';

const nodeFs = require('node:fs');

const PRIVATE_DIR_MODE = 0o700;

function ensureDirMode(dir, mode = PRIVATE_DIR_MODE, { fs = nodeFs, log = () => {} } = {}) {
  try {
    let st = null;
    try {
      st = fs.lstatSync(dir);
    } catch (err) {
      if (err.code !== 'ENOENT') throw err;
    }
    if (st === null) {
      fs.mkdirSync(dir, { recursive: true, mode });
      fs.chmodSync(dir, mode);
      return 'created';
    }
    if (st.isSymbolicLink()) {
      log(`[fs-perms] ${dir} is a symlink: mode left as it is`);
      return 'symlink';
    }
    if (!st.isDirectory()) {
      log(`[fs-perms] ${dir} is not a directory: mode left as it is`);
      return 'not-a-directory';
    }
    if ((st.mode & 0o777) === mode) return 'unchanged';
    fs.chmodSync(dir, mode);
    return 'changed';
  } catch (err) {
    log(`[fs-perms] could not set mode ${mode.toString(8)} on ${dir}: ${err.code || err.message}`);
    return 'failed';
  }
}

module.exports = { PRIVATE_DIR_MODE, ensureDirMode };
