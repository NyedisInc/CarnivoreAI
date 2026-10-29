import { registerMainAreaLayer } from '../sidebar-widgets/main-area-layers';
import { readLastView, restoreLastView, type RestoreDeps } from '../drawer/last-view';

export function registerHomeEscape(deps?: RestoreDeps): () => void {
  return registerMainAreaLayer({
    origin: 'menu',
    open: () => (deps ? deps.screen() : (window as { App?: { currentScreen?: string } }).App?.currentScreen) === 'launchpad' && readLastView() !== null,
    close: () => void restoreLastView(deps),
  });
}

registerHomeEscape();
