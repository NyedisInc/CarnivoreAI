'use strict';

const childProcess = require('node:child_process');
const { spawnDetachedEngine } = require('../engine/detached-spawn');

function spawnEngine(strategy, options) {
  if (strategy !== 'child') return spawnDetachedEngine(options);
  const spawnImpl = (cmd, args, opts) => childProcess.spawn(cmd, args, { ...opts, detached: false });
  return spawnDetachedEngine({ ...options, spawnImpl });
}

module.exports = { spawnEngine };
