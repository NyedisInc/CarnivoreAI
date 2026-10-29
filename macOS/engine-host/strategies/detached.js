'use strict';

const NAME = 'detached';
const SURVIVES_QUIT = true;

function start(manager) {
  return manager.start();
}

module.exports = { NAME, SURVIVES_QUIT, start };
