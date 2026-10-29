/* the home screen */
import { insetsOf, SURFACE_INSET_VARS } from '../menu-page/menu-page-surface';

export const HOME_IN_MAIN_CLASS = 'home-in-main';

const MIN_WIDTH_PX = 1024;

const SURFACE_SELECTOR = '#terminal-grid > .oc-surface';

const HOME_ID = 'launchpad-screen';
const TERMINAL_ID = 'terminal-screen';

export function pausePrimarySocket(): void {
  (globalThis as { TerminalController?: { pauseForHome?: () => void } }).TerminalController?.pauseForHome?.();
}

export function initHomeInMain(doc: Document = document, pausePrimary: () => void = pausePrimarySocket): () => void {
  const win = doc.defaultView;
  if (!win || typeof win.MutationObserver !== 'function') return () => {};
  let inMain = false;
  let wasTerminal = false;
  let covered: HTMLElement | null = null;
  let resizer: ResizeObserver | null = null;

  const active = (id: string): boolean => doc.getElementById(id)?.classList.contains('active') === true;
  const surface = (): HTMLElement | null => doc.querySelector<HTMLElement>(SURFACE_SELECTOR);

  const measure = (): boolean => {
    const el = surface();
    const box = el?.getBoundingClientRect();
    if (!el || !box || box.width <= 0 || box.height <= 0 || win.innerWidth < MIN_WIDTH_PX) return false;
    const insets = insetsOf(el, win);
    const style = doc.documentElement.style;
    SURFACE_INSET_VARS.forEach((name, i) => style.setProperty(name, `${[insets.top, insets.left, insets.right, insets.bottom][i]}px`));
    if (covered !== el) {
      covered?.removeAttribute('inert');
      el.setAttribute('inert', '');
      covered = el;
      resizer?.disconnect();
      if (typeof win.ResizeObserver === 'function') {
        resizer = new win.ResizeObserver(() => refresh());
        [el, el.parentElement, doc.body].forEach((one) => one && resizer?.observe(one));
      }
    }
    return true;
  };

  const leave = (hideTerminal: boolean): void => {
    if (!inMain) return;
    inMain = false;
    resizer?.disconnect();
    resizer = null;
    covered?.removeAttribute('inert');
    covered = null;
    doc.body.classList.remove(HOME_IN_MAIN_CLASS);
    if (hideTerminal) doc.getElementById(TERMINAL_ID)?.classList.remove('active');
  };

  function refresh(): void {
    if (inMain && !measure()) leave(true);
  }

  const enter = (): void => {
    inMain = true;
    pausePrimary();
    doc.getElementById(TERMINAL_ID)?.classList.add('active');
    doc.body.classList.add(HOME_IN_MAIN_CLASS);
    if (!measure()) leave(true);
  };

  const sync = (): void => {
    if (!active(HOME_ID)) {
      leave(false);
      wasTerminal = active(TERMINAL_ID);
      return;
    }
    if (inMain) {
      if (!active(TERMINAL_ID)) doc.getElementById(TERMINAL_ID)?.classList.add('active');
      return refresh();
    }
    if (wasTerminal && !active(TERMINAL_ID) && surface() && win.innerWidth >= MIN_WIDTH_PX) enter();
  };

  wasTerminal = active(TERMINAL_ID);
  const observer = new win.MutationObserver(sync);
  for (const id of [HOME_ID, TERMINAL_ID]) {
    const el = doc.getElementById(id);
    if (el) observer.observe(el, { attributes: true, attributeFilter: ['class'] });
  }
  return () => {
    observer.disconnect();
    leave(false);
  };
}
