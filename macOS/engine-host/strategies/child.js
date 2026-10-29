'use strict';

const NAME = 'child';
const SURVIVES_QUIT = false;

function start(manager) {
  return manager.start();
}

module.exports = { NAME, SURVIVES_QUIT, start };
