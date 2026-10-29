import type { LiveTerminal } from './client';

export const PARKED_LAYOUTS = 2;

export const PARKED_TERMINALS = 8;

export const PARK_MS = 5 * 60_000;

const LAYOUT_PREFIX = 'layout:';

interface Parked {
  owner: string;
  key: string;
  host: HTMLElement;
  box: HTMLElement;
  handle: LiveTerminal;
  timer: ReturnType<typeof setTimeout>;
}

const shelf: Parked[] = [];
let enabled = false;
let shelfEl: HTMLElement | null = null;

interface SizeVote {
  setTabHidden(client: unknown, hidden: boolean, doc?: Document): void;
}

export function parkKey(slot: string, terminalKey: string): string {
  return slot + '\n' + terminalKey;
}

export function setParking(on: boolean): void {
  enabled = on;
  if (!on) releaseAll();
}

export function shouldPark(owner: string, current: string): boolean {
  return enabled && owner.startsWith(LAYOUT_PREFIX) && !owner.startsWith(LAYOUT_PREFIX + '@') && owner !== current;
}

function shelfElement(): HTMLElement {
  if (shelfEl && shelfEl.isConnected) return shelfEl;
  const el = document.createElement('div');
  el.setAttribute('data-parked-terminals', '');
  el.setAttribute('aria-hidden', 'true');
  el.inert = true;
  el.style.cssText = 'position:fixed;left:0;top:0;width:0;height:0;overflow:hidden;visibility:hidden;pointer-events:none';
  document.body.appendChild(el);
  shelfEl = el;
  return el;
}

function drop(entry: Parked): void {
  const at = shelf.indexOf(entry);
  if (at >= 0) shelf.splice(at, 1);
  clearTimeout(entry.timer);
  entry.handle.dispose();
  entry.box.remove();
}

function enforce(): void {
  const owners: string[] = [];
  for (let i = shelf.length - 1; i >= 0; i -= 1) {
    const owner = shelf[i]!.owner;
    if (!owners.includes(owner)) owners.push(owner);
  }
  const keep = owners.slice(0, PARKED_LAYOUTS);
  for (const entry of [...shelf]) if (!keep.includes(entry.owner)) drop(entry);
  while (shelf.length > PARKED_TERMINALS) drop(shelf[0]!);
}

export function park(owner: string, key: string, host: HTMLElement, handle: LiveTerminal): void {
  const rect = host.getBoundingClientRect();
  const box = document.createElement('div');
  box.style.position = 'absolute';
  box.style.display = 'flex';
  if (rect.width > 0 && rect.height > 0) {
    box.style.width = `${rect.width}px`;
    box.style.height = `${rect.height}px`;
  }
  (globalThis as { TerminalSizeVote?: SizeVote }).TerminalSizeVote?.setTabHidden(handle.client, true, document);
  box.appendChild(host);
  shelfElement().appendChild(box);
  for (const old of shelf.filter((one) => one.owner === owner && one.key === key)) drop(old);
  const entry: Parked = { owner, key, host, box, handle, timer: setTimeout(() => drop(entry), PARK_MS) };
  shelf.push(entry);
  enforce();
}

/* the live client */
export function unpark(owner: string, key: string): { host: HTMLElement; handle: LiveTerminal } | null {
  const entry = shelf.find((one) => one.owner === owner && one.key === key);
  if (!entry) return null;
  shelf.splice(shelf.indexOf(entry), 1);
  clearTimeout(entry.timer);
  entry.box.remove();
  return { host: entry.host, handle: entry.handle };
}

export function releaseAll(): void {
  for (const entry of [...shelf]) drop(entry);
}

export function parkedCount(): number {
  return shelf.length;
}
