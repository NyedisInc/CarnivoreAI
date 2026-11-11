
'use strict';

const fs = require('fs');
const os = require('os');
const path = require('path');

const SOUNDS_DIR = path.join(__dirname, '..', 'sounds');
const NAME = /^carnivore-[a-z]+\.aiff$/;

function installNamedSounds(opts) {
  if (opts.isPackaged || (opts.platform || process.platform) !== 'darwin') return [];
  const from = opts.from || SOUNDS_DIR;
  const to = path.join(opts.home || os.homedir(), 'Library', 'Sounds');
  const copied = [];
  try {
    fs.mkdirSync(to, { recursive: true });
    for (const name of fs.readdirSync(from).filter((n) => NAME.test(n))) {
      const source = fs.readFileSync(path.join(from, name));
      const target = path.join(to, name);
      if (fs.existsSync(target) && fs.readFileSync(target).equals(source)) continue;
      fs.writeFileSync(target, source);
      copied.push(name);
    }
  } catch (error) {
    console.warn('[banners] could not install the notification sounds:', String((error && error.message) || error));
  }
  return copied;
}

module.exports = { installNamedSounds };
