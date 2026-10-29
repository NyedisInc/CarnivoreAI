export const RAIL_CONTAINER_ID = 'session-sidebar-wrail';
export const FLYOUT_CONTAINER_ID = 'session-sidebar-flyout';
export const REGION_ID = 'session-sidebar-region';
export const RAIL_LAYER_ID = 'session-sidebar-rail-layer';
export const RAIL_BODY_CLASS = 'sidebar-layout-rail';
export const RAIL_PINNED_BODY_CLASS = 'sidebar-rail-pinned';

export function railDomApplied(doc: Document = document): boolean {
  return doc.getElementById(REGION_ID) !== null;
}

export function applyRailDom(doc: Document = document): boolean {
  if (!railDomApplied(doc)) return false;
  doc.body.classList.add(RAIL_BODY_CLASS);
  return true;
}

export function setRailPinnedClass(pinned: boolean, doc: Document = document): void {
  doc.body.classList.toggle(RAIL_PINNED_BODY_CLASS, pinned);
}
