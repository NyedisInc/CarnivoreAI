
'use strict';

const { glyphFor } = require('./led-hues');
const { renderGlyphPng } = require('./led-glyph');

function createLedIcons({ nativeImage, nativeTheme }) {
  const cache = new Map();
  return {
    iconFor(state) {
      if (!state) return undefined;
      const glyph = glyphFor(state.inner);
      const key = `${nativeTheme.shouldUseDarkColors ? 'dark' : 'light'}:${state.inner}`;
      if (cache.has(key)) return cache.get(key);
      let image;
      try {
        image = nativeImage.createFromBuffer(renderGlyphPng(glyph, 1), { scaleFactor: 1 });
        image.addRepresentation({ scaleFactor: 2, buffer: renderGlyphPng(glyph, 2) });
      } catch (error) {
        console.warn('[tray-menu] status dot could not be drawn:', error && error.message);
        image = undefined;
      }
      cache.set(key, image);
      return image;
    },
    invalidate() { cache.clear(); },
    size: () => cache.size,
  };
}

module.exports = { createLedIcons };
