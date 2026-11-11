
'use strict';

const { contextBridge, ipcRenderer } = require('electron');

const MAX_ID = 40;

contextBridge.exposeInMainWorld('CarnivoreCorner', {
  onCard(fn) {
    if (typeof fn !== 'function') return;
    ipcRenderer.on('carnivore:corner-card', (_event, shown) => fn(shown));
  },
  press(id) {
    if (typeof id === 'string' && id.length > 0 && id.length <= MAX_ID) ipcRenderer.send('carnivore:corner-press', id);
  },
  close() {
    ipcRenderer.send('carnivore:corner-close');
  },
});
