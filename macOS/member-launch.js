
'use strict';

const fs = require('fs');
const path = require('path');

const SENTINEL_NAME = '.member-launch-seeded';

function applyMemberLaunch({ joined, dir, installer, launchArgs, fsImpl }) {
  const f = fsImpl || fs;
  const sentinel = path.join(dir, SENTINEL_NAME);
  if (joined === false) {
    try {
      f.unlinkSync(sentinel);
      return 'cleared';
    } catch (err) {
      return 'none';
    }
  }
  if (joined !== true) return 'none';
  if (f.existsSync(sentinel)) return 'kept';
  let result = 'kept';
  if (!installer.isEnabled()) {
    installer.enable(launchArgs());
    result = 'enabled';
  }
  try {
    f.mkdirSync(dir, { recursive: true });
    f.writeFileSync(sentinel, `${new Date().toISOString()}\n`, { mode: 0o600 });
  } catch (err) {
    console.warn('[member-launch] could not record the seed:', err.message);
  }
  return result;
}

module.exports = { SENTINEL_NAME, applyMemberLaunch };
