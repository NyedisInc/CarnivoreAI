
'use strict';

const fs = require('fs');
const path = require('path');

const FILE_NAME = 'desktop-hotkey.json';
const ACCELERATOR_MAX = 64;

function createHotkeyStore(dirOf) {
  function file() {
    try {
      return path.join(dirOf(), FILE_NAME);
    } catch (error) {
      return null;
    }
  }
  return {
    load() {
      const target = file();
      if (!target) return null;
      try {
        const value = JSON.parse(fs.readFileSync(target, 'utf8')).accelerator;
        return typeof value === 'string' && value.length <= ACCELERATOR_MAX ? value : null;
      } catch (error) {
        return null;
      }
    },
    save(accelerator) {
      const target = file();
      if (!target || typeof accelerator !== 'string' || accelerator.length > ACCELERATOR_MAX) return;
      try {
        const temp = `${target}.tmp`;
        fs.writeFileSync(temp, JSON.stringify({ accelerator }), { mode: 0o600 });
        fs.renameSync(temp, target);
      } catch (error) {
        console.warn('[hotkey] could not save the accelerator:', error && error.message);
      }
    },
  };
}

module.exports = { createHotkeyStore };
