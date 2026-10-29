import { mountPanel, unmountPanel } from '../mount';
import ForkPicker from './ForkPicker.svelte';

const ID = 'crosstalk-fork-picker';

export function openForkPicker(sessionId: string, name: string): boolean {
  if (!sessionId || typeof document === 'undefined') return false;
  let host = document.getElementById(ID);
  if (!host) {
    host = document.createElement('div');
    host.id = ID;
    document.body.appendChild(host);
  }
  return mountPanel(ID, ForkPicker, { sessionId, name, onClose: () => unmountPanel(ID) }) !== null;
}
