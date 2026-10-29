
export const MODAL_SELECTOR = '.modal-overlay, dialog[open], [role="dialog"][aria-modal="true"], [role="alertdialog"]';

const DOCKED_DRAWER_SELECTOR = '.config-editor-picker-overlay';

const NON_TEXT_INPUTS = ['button', 'checkbox', 'radio', 'submit', 'reset', 'range', 'color', 'file'];

export function inTerminal(el: EventTarget | null): boolean {
  return el instanceof Element && !!el.closest('.xterm');
}

export function menuShowing(el: Element): boolean {
  if (el.closest('[hidden], [inert]')) return false;
  const check = (el as Element & { checkVisibility?: (opts?: object) => boolean }).checkVisibility;
  return typeof check === 'function' ? check.call(el, { visibilityProperty: true }) : true;
}

export function ownsEscape(el: EventTarget | null): boolean {
  if (!(el instanceof HTMLElement)) return false;
  if (el.closest('.xterm')) return false;
  if (el.isContentEditable || el instanceof HTMLTextAreaElement || el instanceof HTMLSelectElement) return true;
  if (el.getAttribute('role') === 'combobox' && el.getAttribute('aria-expanded') === 'true') return true;
  return el instanceof HTMLInputElement && el.value !== '' && !NON_TEXT_INPUTS.includes(el.type);
}

export function modalShowing(doc: Document): boolean {
  return [...doc.querySelectorAll(MODAL_SELECTOR)].some((el) => menuShowing(el) && !dockedDrawer(el, doc));
}

export function layerShowing(doc: Document): boolean {
  return [...doc.querySelectorAll(`${MODAL_SELECTOR}, [role="menu"]`)].some((el) => menuShowing(el) && !dockedDrawer(el, doc));
}

function dockedDrawer(el: Element, doc: Document): boolean {
  return !!el.closest(DOCKED_DRAWER_SELECTOR) && !!doc.body?.classList.contains('right-drawer-docked');
}

const POPUP_SELECTOR = '[role="dialog"], [aria-haspopup]:not([aria-haspopup="false"])[aria-expanded="true"]';

export function floatingShowing(doc: Document): boolean {
  if (layerShowing(doc)) return true;
  return [...doc.querySelectorAll(POPUP_SELECTOR)].some((el) => menuShowing(el) && !dockedDrawer(el, doc));
}
