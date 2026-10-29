import { setRemoteMenuHost, type RemoteMenuControls } from '../lib/drawer-tabs/menu-remote';
import { MENU_CHOOSE, MENU_CLOSE, MENU_HIDE, MENU_SHOW, readMenuMessage, type MenuChooseMessage, type MenuCloseMessage } from '../lib/drawer-tabs/menu-remote-messages';

const OWN_PRESS_MS = 400;

const open = new Map<number, RemoteMenuControls>();
let lastPress = 0;

export function remoteMenuOpen(): boolean {
  return open.size > 0;
}

export function installRemoteMenus(): void {
  if (window.parent === window) return;
  window.addEventListener('pointerdown', () => (lastPress = performance.now()), true);
  window.addEventListener('message', (event: MessageEvent) => {
    if (event.origin !== location.origin || event.source !== window.parent) return;
    const choose = readMenuMessage<MenuChooseMessage>(event.data, MENU_CHOOSE);
    if (choose && Array.isArray(choose.path)) {
      open.get(choose.id)?.choose(choose.path.map(String));
      return;
    }
    const close = readMenuMessage<MenuCloseMessage>(event.data, MENU_CLOSE);
    if (close && performance.now() - lastPress > OWN_PRESS_MS) open.get(close.id)?.close();
  });
  setRemoteMenuHost({
    show(id, spec, controls) {
      open.set(id, controls);
      window.parent.postMessage({ type: MENU_SHOW, id, ...spec }, location.origin);
    },
    hide(id) {
      if (!open.delete(id)) return;
      window.parent.postMessage({ type: MENU_HIDE, id }, location.origin);
    },
  });
}
