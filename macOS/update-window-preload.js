
'use strict';

const { contextBridge, ipcRenderer } = require('electron');

const FACTS_CHANNEL = 'carnivore:update-facts';
const ACTION_CHANNEL = 'carnivore:update-action';

contextBridge.exposeInMainWorld('carnivoreUpdate', {
  onFacts(callback) {
    ipcRenderer.on(FACTS_CHANNEL, (_event, facts) => callback(facts));
  },
  requestFacts() {
    return ipcRenderer.invoke(FACTS_CHANNEL);
  },
  runAction(id) {
    ipcRenderer.send(ACTION_CHANNEL, String(id));
  },
});
