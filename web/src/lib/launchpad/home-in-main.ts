/* the bottom rail */


import { SURFACE_MIN_WIDTH_PX } from '../menu-page/menu-page-surface';

const GRID_ID = 'terminal-grid';

const HOME_ID = 'launchpad-screen';
const TERMINAL_ID = 'terminal-screen';

const EMPTY_CLASS = 'terminal-screen--empty';

export const HOME_SLOT_ATTR = 'data-home-slot';

export function pausePrimarySocket(): void {
  (globalThis as { TerminalController?: { pauseForHome?: () => void } }).TerminalController?.pauseForHome?.();
}

export function initHomeInMain(doc: Document = document, pausePrimary: () => void = pausePrimarySocket): () => void {
  const win = doc.defaultView;
  if (!win || typeof win.MutationObserver !== 'function') return () => {};
  let inSlot = false;
  let wasTerminal = false;
  let homeParent: Node | null = null;
  let homeNext: Node | null = null;

  const el = (id: string): HTMLElement | null => doc.getElementById(id);
  const active = (id: string): boolean => el(id)?.classList.contains('active') === true;
  const wide = (): boolean => win.innerWidth >= SURFACE_MIN_WIDTH_PX;
  const terminalShowsSession = (): boolean => active(TERMINAL_ID) && !el(TERMINAL_ID)!.classList.contains(EMPTY_CLASS);

  const surface = (): HTMLElement | null => doc.querySelector<HTMLElement>(`#${GRID_ID} > .oc-surface`);
  let gridWatch: MutationObserver | null = null;
  const coverSurface = (): void => {
    surface()?.setAttribute('inert', '');
    const grid = el(GRID_ID);
    if (grid && !gridWatch) {
      gridWatch = new win.MutationObserver(() => surface()?.setAttribute('inert', ''));
      gridWatch.observe(grid, { childList: true });
    }
  };
  const uncoverSurface = (): void => {
    gridWatch?.disconnect();
    gridWatch = null;
    surface()?.removeAttribute('inert');
  };

  const enter = (): void => {
    const home = el(HOME_ID);
    const grid = el(GRID_ID);
    if (!home || !grid) return;
    inSlot = true;
    pausePrimary();
    homeParent = home.parentNode;
    homeNext = home.nextSibling;
    el(TERMINAL_ID)?.classList.add('active');
    grid.setAttribute(HOME_SLOT_ATTR, '');
    grid.append(home);
    coverSurface();
  };

  const leave = (hideTerminal: boolean): void => {
    if (!inSlot) return;
    inSlot = false;
    const home = el(HOME_ID);
    el(GRID_ID)?.removeAttribute(HOME_SLOT_ATTR);
    uncoverSurface();
    if (home && homeParent) homeParent.insertBefore(home, homeNext && homeNext.parentNode === homeParent ? homeNext : null);
    homeParent = null;
    homeNext = null;
    if (hideTerminal) el(TERMINAL_ID)?.classList.remove('active');
  };

  const reconcile = (): void => {
    const homeUp = active(HOME_ID);
    if (inSlot) {
      if (!homeUp) return leave(false);
      if (!wide()) return leave(true);
      if (!active(TERMINAL_ID)) el(TERMINAL_ID)?.classList.add('active');
      return;
    }
    if (homeUp && wasTerminal && wide()) enter();
  };

  const sync = (): void => {
    if (!active(HOME_ID)) {
      leave(false);
      wasTerminal = terminalShowsSession();
      return;
    }
    reconcile();
  };

  wasTerminal = terminalShowsSession();
  const observer = new win.MutationObserver(sync);
  for (const id of [HOME_ID, TERMINAL_ID]) {
    const node = el(id);
    if (node) observer.observe(node, { attributes: true, attributeFilter: ['class'] });
  }
  win.addEventListener('resize', reconcile);
  return () => {
    win.removeEventListener('resize', reconcile);
    observer.disconnect();
    leave(false);
  };
}
