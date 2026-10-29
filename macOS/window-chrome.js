
'use strict';

const TABBING_ID = Object.freeze({ main: 'carnivore-main', popout: 'carnivore-popout', solo: 'carnivore-solo' });
const TITLE_BAR_STYLE = 'hiddenInset';
const TRAFFIC_LIGHTS = Object.freeze({ x: 16, y: 8 });
const INSET = Object.freeze({ top: 28, left: 78 });

/* tabbingIdentifier: */
function chromeOptions(kind) {
  if (typeof kind !== 'string' || !Object.prototype.hasOwnProperty.call(TABBING_ID, kind)) throw new Error(`unknown window kind: ${String(kind)}`);
  return { titleBarStyle: TITLE_BAR_STYLE, trafficLightPosition: { ...TRAFFIC_LIGHTS }, tabbingIdentifier: TABBING_ID[kind], fullscreenable: true };
}

function chromeState(win) {
  const fullScreen = win.isFullScreen() === true;
  return { titleBar: TITLE_BAR_STYLE, inset: fullScreen ? { top: 0, left: 0 } : { top: INSET.top, left: INSET.left }, fullScreen };
}

module.exports = { TABBING_ID, TITLE_BAR_STYLE, TRAFFIC_LIGHTS, INSET, chromeOptions, chromeState };
