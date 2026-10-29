
'use strict';

const TOKEN_HEX = Object.freeze({
  '--oc-ground-chrome': '#02161e',
  '--oc-ground-titlerow': '#02161e',
  '--oc-ground-field': '#030c0d',
  '--oc-ground-raised': '#061214',
  '--oc-ground-hover': '#0b1a1c',
  '--oc-line-rule': '#1f2e30',
  '--oc-line-frame': '#3f4649',
  '--oc-text-bright': '#ffffff',
  '--oc-text-primary': '#cbd6d9',
  '--oc-text-secondary': '#a3b4bb',
  '--oc-text-muted': '#82898f',
  '--oc-text-dim': '#6b7378',
  '--oc-orange': '#ff4652',
  '--oc-green': '#4acf93',
  '--oc-yellow-bright': '#e4c13c',
  '--oc-cyan': '#6cb0e0',
  '--oc-coral': '#e78475',
});

function tokensCss() {
  return `:root{${Object.entries(TOKEN_HEX).map(([k, v]) => `${k}:${v};`).join('')}}`;
}

module.exports = { TOKEN_HEX, tokensCss };
