import { tick } from 'svelte';
import { beginGesture, captureRows, pickTarget, type CellDragMerge } from './pointer';
import { terminalLayout, type DropTarget } from './layout.svelte';
import { mergeComponent, placeTab, splitTabOut } from './tab-groups.svelte';
import { tabDrag } from './tab-drag-state.svelte';
import { dropZone, zoneTarget, type Box, type Zone } from './tab-split';
import { viewport } from './viewport.svelte';
import { MAX_VIEWERS, PRIMARY_SLOT } from './model';
import { limitLine } from './components-actions';
import type { SlotId } from './types';
import { inputFocus } from '../lib/input-focus.svelte';
import { primarySessionId } from '../api/host';
import { sessions } from '../api';
import { asleep, wakeOrPick } from '../api/asleep.svelte';
import { slotForSession } from './slot-identity';
import { t } from '../../lib/i18n/index.svelte';
import { splitThrough } from '../layouts/transition.svelte';
import { pageIdOfTab, pageTabOfRowName } from './page-tabs';
import { pageTabItem } from '../cells/terminal-group/page-tab-item';
import { tearOffTab } from '../../lib/tearoff/tab-tearoff';

export const TAB_THRESHOLD = 6;

const GRID_ID = 'terminal-grid';

export interface StripTarget {
  slot: string;
  left: number;
  right: number;
  top: number;
  bottom: number;
  tabs: { id: string; centre: number }[];
}

export type TabDrop =
  | { kind: 'strip'; slot: string; index: number }
  | { kind: 'zone'; slot: string; zone: Zone }
  | { kind: 'out'; target: DropTarget };

/* frame, and the */
export interface BodyTarget extends Box {
  slot: string;
  tabs: string[];
}

export interface DragSurface {
  strips: StripTarget[];
  bodies: BodyTarget[];
  out: (x: number, y: number) => DropTarget | null;
}

export function pickStripDrop(strips: readonly StripTarget[], x: number, y: number, tab: string): TabDrop | null {
  const strip = strips.find((s) => x >= s.left && x <= s.right && y >= s.top && y <= s.bottom);
  if (!strip) return null;
  const index = strip.tabs.filter((other) => other.id !== tab && x > other.centre).length;
  return { kind: 'strip', slot: strip.slot, index };
}

export function pickBodyDrop(body: BodyTarget, x: number, y: number, tab: string): TabDrop | null {
  const zone = dropZone(body, x, y);
  if (!zone) return null;
  const own = body.tabs.includes(tab);
  if (own && (zone === 'center' || body.tabs.length === 1)) return null;
  return { kind: 'zone', slot: body.slot, zone };
}

export function pickDrop(surface: DragSurface, x: number, y: number, tab: string): TabDrop | null {
  const strip = pickStripDrop(surface.strips, x, y, tab);
  if (strip) return strip;
  const body = surface.bodies.find((one) => dropZone(one, x, y) !== null);
  if (body) return pickBodyDrop(body, x, y, tab);
  const target = surface.out(x, y);
  return target ? { kind: 'out', target } : null;
}

export function measureBodies(root: ParentNode): BodyTarget[] {
  const bodies: BodyTarget[] = [];
  for (const el of root.querySelectorAll<HTMLElement>('[data-tab-group]')) {
    const box = (el.closest('.oc-frame') ?? el).getBoundingClientRect();
    if (box.width <= 0 || box.height <= 0) continue;
    const tabs = [...el.querySelectorAll<HTMLElement>('[data-tab]')].map((button) => button.dataset['tab'] ?? '');
    bodies.push({ slot: el.dataset['tabGroup'] ?? '', left: box.left, right: box.right, top: box.top, bottom: box.bottom, tabs });
  }
  return bodies;
}

function measure(root: HTMLElement): DragSurface {
  const surface = root.querySelector<HTMLElement>('.oc-surface');
  const scroller = surface?.closest<HTMLElement>('.oc-content') ?? null;
  const top = scroller ? scroller.getBoundingClientRect().top - scroller.scrollTop : 0;
  const { rows, cells } = surface
    ? captureRows(terminalLayout, surface, scroller, scroller?.scrollTop ?? 0)
    : { rows: [], cells: [] };
  return {
    strips: measureStrips(root),
    bodies: measureBodies(root),
    out: (x, y) => pickTarget(rows, cells, y - top, x, null),
  };
}

export function measureStrips(root: ParentNode): StripTarget[] {
  const strips: StripTarget[] = [];
  for (const el of root.querySelectorAll<HTMLElement>('[data-tab-group]')) {
    const box = (el.closest('.oc-frame-strip') ?? el).getBoundingClientRect();
    if (box.width <= 0 || box.height <= 0) continue;
    const tabs = [...el.querySelectorAll<HTMLElement>('[data-tab]')].map((button) => {
      const r = (button.closest('.oc-tabwrap') ?? button).getBoundingClientRect();
      return { id: button.dataset['tab'] ?? '', centre: r.left + r.width / 2 };
    });
    strips.push({ slot: el.dataset['tabGroup'] ?? '', left: box.left, right: box.right, top: box.top, bottom: box.bottom, tabs });
  }
  return strips;
}

export function focusTab(tab: string): void {
  [...document.querySelectorAll<HTMLElement>(`#${GRID_ID} [data-tab-pane]`)]
    .find((el) => el.dataset['tabPane'] === tab)
    ?.querySelector<HTMLElement>('textarea')
    ?.focus({ preventScroll: true });
}

function swallowNextClick(): void {
  const stop = (event: Event): void => {
    event.stopPropagation();
    event.preventDefault();
  };
  globalThis.addEventListener('click', stop, { capture: true, once: true });
  setTimeout(() => globalThis.removeEventListener('click', stop, { capture: true }), 0);
}

function splitLine(result: 'split' | 'moved' | 'cap' | 'limit' | null, name: string): string {
  if (result === 'limit') return limitLine('terminal');
  if (result === 'cap') return t('opscenter.components.add_cap', { count: MAX_VIEWERS });
  return result ? t('opscenter.tabs.split', { name }) : '';
}

function commit(tab: string, drop: TabDrop): boolean {
  const button = [...document.querySelectorAll<HTMLElement>(`#${GRID_ID} [data-tab]`)].find(
    (el) => el.dataset['tab'] === tab,
  );
  const pageId = pageIdOfTab(tab);
  const name = button?.title || (pageId === null ? tab : pageTabItem(tab, pageId).name);
  let line: string;
  if (drop.kind === 'strip' || (drop.kind === 'zone' && drop.zone === 'center')) {
    const done = placeTab(terminalLayout, drop.slot, tab, drop.kind === 'strip' ? drop.index : Number.MAX_SAFE_INTEGER);
    if (!done) return false;
    line = t(done === 'added' ? 'opscenter.tabs.added' : 'opscenter.tabs.moved', { name });
  } else {
    const target = drop.kind === 'out' ? drop.target : zoneTarget(terminalLayout.state.layout, drop.slot as SlotId, drop.zone);
    const result = target
      ? splitThrough(() => splitTabOut(terminalLayout, tab, target), (done) => done === 'split', null)
      : null;
    line = splitLine(result, name);
    if (result === 'cap' || result === 'limit') terminalLayout.announce(line);
    if (result === 'cap' || result === 'limit' || !result) return false;
  }
  inputFocus.claim(tab);
  void tick().then(() => {
    terminalLayout.announce(line);
    focusTab(tab);
  });
  return true;
}

function aimAt(tab: string, drop: TabDrop | null): void {
  tabDrag.tab = tab;
  tabDrag.target = drop;
  tabDrag.zone = drop?.kind === 'zone' ? { slot: drop.slot, zone: drop.zone } : null;
  terminalLayout.drag.target = drop?.kind === 'out' ? drop.target : null;
}

function run(element: HTMLElement, event: PointerEvent, tab: string, threshold: number, wake?: () => void): boolean {
  const root = document.getElementById(GRID_ID);
  if (!root) return false;
  let surface: DragSurface = { strips: [], bodies: [], out: () => null };
  return beginGesture(element, event, {
    threshold,
    onLift: (lift) => {
      surface = measure(root);
      aimAt(tab, pickDrop(surface, lift.clientX, lift.clientY, tab));
    },
    onMove: (_dx, _dy, move) => {
      aimAt(tab, pickDrop(surface, move.clientX, move.clientY, tab));
    },
    onDrop: (_dx, _dy, up) => {
      swallowNextClick();
      if (tearOffTab(tab, up)) return;
      const drop = pickDrop(surface, up.clientX, up.clientY, tab);
      if (drop && commit(tab, drop)) wake?.();
    },
    onEnd: () => {
      tabDrag.tab = null;
      tabDrag.target = null;
      tabDrag.zone = null;
      terminalLayout.clearDrag();
    },
  });
}

export function componentMerge(id: string): CellDragMerge {
  let bodies: BodyTarget[] | null = null;
  return {
    aim(x, y) {
      const root = document.getElementById(GRID_ID);
      bodies ??= root ? measureBodies(root) : [];
      const body = bodies.find((one) => one.slot !== id && dropZone(one, x, y) === 'center');
      tabDrag.zone = body ? { slot: body.slot, zone: 'center' } : null;
      return body !== undefined;
    },
    drop() {
      const into = tabDrag.zone?.slot;
      if (!into) return false;
      const done = mergeComponent(terminalLayout, id, into);
      if (done) terminalLayout.announce(t(done === 'merged' ? 'opscenter.tabs.merged' : 'opscenter.tabs.merge_primary'));
      return true;
    },
    end() {
      tabDrag.zone = null;
    },
  };
}

/* there is nothing */
export function beginTabDrag(handle: HTMLElement, event: PointerEvent, tab: string): boolean {
  if (!viewport.wide || event.pointerType === 'touch') return false;
  return run(handle, event, tab, TAB_THRESHOLD);
}

export interface DrawerDragStart {
  name: string;
  pointerId: number;
  pointerType: string;
  clientX: number;
  clientY: number;
}

function pointerOf(start: DrawerDragStart): PointerEvent {
  return {
    pointerId: start.pointerId,
    pointerType: start.pointerType,
    clientX: start.clientX,
    clientY: start.clientY,
    button: 0,
  } as PointerEvent;
}

export function beginDrawerTabDrag(start: DrawerDragStart): boolean {
  if (!viewport.wide || start.pointerType === 'touch') return false;
  const root = document.getElementById(GRID_ID);
  if (!root || measureStrips(root).length === 0) return false;
  const pageTab = pageTabOfRowName(start.name);
  if (pageTab !== null) return run(document.body, pointerOf(start), pageTab, 0);
  const id = (sessions.data ?? []).find((row) => row.tmux_session === start.name)?.session?.id;
  if (!id) return beginAsleepTabDrag(start);
  const tab = id === primarySessionId() ? PRIMARY_SLOT : slotForSession(id, sessions.data);
  return run(document.body, pointerOf(start), tab, 0);
}

function beginAsleepTabDrag(start: DrawerDragStart): boolean {
  const rec = (asleep.data ?? []).find((r) => r.asleep && r.tmux_name === start.name);
  if (!rec || typeof rec.id !== 'number') return false;
  const event = {
    pointerId: start.pointerId, pointerType: start.pointerType, clientX: start.clientX, clientY: start.clientY, button: 0,
  } as PointerEvent;
  const wake = (): void => {
    wakeOrPick(rec.session_uuid, start.name, rec.title || start.name).catch((err: unknown) => {
      console.warn('wake after drag of an asleep row failed', err);
    });
  };
  return run(document.body, event, `terminal:row:${rec.id}`, 0, wake);
}
