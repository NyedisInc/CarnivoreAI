
'use strict';

const { contextBridge, ipcRenderer } = require('electron');

const FACTS_CHANNEL = 'carnivore:status-facts';
const ACTION_CHANNEL = 'carnivore:status-action';

contextBridge.exposeInMainWorld('carnivoreStatus', {
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
