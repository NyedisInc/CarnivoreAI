import { currentDensity, type DensityMode } from '../drawer-tabs/density-mode';
import { PANEL_ATTR as LEADERS_ATTR, leadersShown } from '../drawer/leader-visibility';
import { PANEL_ATTR as ARCHIVED_ATTR, archivedShown } from '../drawer/archived-visibility';

const PANEL_ID = 'session-sidebar-panel';

export const viewState = $state<{ density: DensityMode; leaders: boolean; archived: boolean }>({
  density: currentDensity() ?? 'compact',
  leaders: leadersShown(),
  archived: archivedShown(),
});

export function readViewState(): void {
  viewState.density = currentDensity() ?? viewState.density;
  viewState.leaders = leadersShown();
  viewState.archived = archivedShown();
}

export function watchViewState(): () => void {
  readViewState();
  const panel = typeof document === 'undefined' ? null : document.getElementById(PANEL_ID);
  if (!panel || typeof MutationObserver !== 'function') return () => {};
  const observer = new MutationObserver(readViewState);
  observer.observe(panel, { attributes: true, attributeFilter: ['data-density', LEADERS_ATTR, ARCHIVED_ATTR] });
  return () => observer.disconnect();
}
