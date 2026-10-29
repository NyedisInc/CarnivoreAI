
'use strict';

function shouldMirror({ asksOnly, askSessionId }) {
  if (asksOnly !== true) return true;
  return typeof askSessionId === 'string' && askSessionId !== '';
}

module.exports = { shouldMirror };
