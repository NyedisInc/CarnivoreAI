
'use strict';

const { TOKEN_HEX } = require('./oc-token-values');

const DEAD_HEX = '#494c4f';

const SHAPES = Object.freeze({ DISC: 'disc', RING: 'ring', RING_DOT: 'ringdot', MOON: 'moon', SKULL: 'skull' });

const GLYPHS = Object.freeze({
  working: { shape: SHAPES.DISC, color: TOKEN_HEX['--oc-green'] },
  'waiting-permission': { shape: SHAPES.DISC, color: TOKEN_HEX['--oc-yellow-bright'] },
  'waiting-input': { shape: SHAPES.DISC, color: TOKEN_HEX['--oc-yellow-bright'] },
  notice: { shape: SHAPES.DISC, color: TOKEN_HEX['--oc-cyan'] },
  idle: { shape: SHAPES.DISC, color: TOKEN_HEX['--oc-text-muted'] },
  done: { shape: SHAPES.RING_DOT, color: TOKEN_HEX['--oc-green'], centerColor: TOKEN_HEX['--oc-text-muted'] },
  dead: { shape: SHAPES.DISC, color: DEAD_HEX },
  disconnected: { shape: SHAPES.DISC, color: TOKEN_HEX['--oc-coral'] },
  asleep: { shape: SHAPES.MOON, color: TOKEN_HEX['--oc-text-muted'] },
  'asleep-unread': { shape: SHAPES.MOON, color: TOKEN_HEX['--oc-green'] },
  limit: { shape: SHAPES.SKULL, color: TOKEN_HEX['--oc-coral'] },
  unknown: { shape: SHAPES.RING, color: TOKEN_HEX['--oc-text-muted'] },
});

function glyphFor(inner) {
  return GLYPHS[inner] || GLYPHS.unknown;
}

module.exports = { DEAD_HEX, SHAPES, GLYPHS, glyphFor };
