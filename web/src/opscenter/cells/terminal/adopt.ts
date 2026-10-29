
export const TERMINAL_CONTAINER_ID = 'terminal-container';

export const TERMINAL_GRID_ID = 'terminal-grid';

let custodian: HTMLElement | null = null;

let home: HTMLElement | null = null;

let held: HTMLElement | null = null;

export function adoptPane(host: HTMLElement, doc: Document = document): (() => void) | null {
  const node = doc.getElementById(TERMINAL_CONTAINER_ID);
  if (!node) return null;
  if (custodian === host && node.parentElement === host) return null;
  if (custodian && custodian !== host && custodian.isConnected) {
    console.warn('opscenter: the terminal pane is already held by another cell');
    return null;
  }
  const from = node.parentElement ?? doc.getElementById(TERMINAL_GRID_ID);
  host.appendChild(node);
  custodian = host;
  home = from;
  held = node;
  return () => releasePane(host, doc);
}

export function releasePane(host: HTMLElement, doc: Document = document): boolean {
  if (custodian !== host) return false;
  const node = held;
  custodian = null;
  held = null;
  const from = home;
  home = null;
  if (!node) return false;
  const back = from && from.isConnected ? from : doc.getElementById(TERMINAL_GRID_ID);
  if (!back) return false;
  back.appendChild(node);
  return true;
}

export function releaseHeldPane(doc: Document = document): boolean {
  if (!custodian) return false;
  return releasePane(custodian, doc);
}

export function paneCustodian(): HTMLElement | null {
  return custodian;
}

export function heldPane(): HTMLElement | null {
  return held;
}
