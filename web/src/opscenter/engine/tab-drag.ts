import { tick } from 'svelte';
import type { CellDragMerge } from './pointer';
import { terminalLayout, type DropTarget, type LayoutStore } from './layout.svelte';
import { dropHostById } from '../../lib/motion-grid';
import { stripOf } from './tabs-motion/strip-motion';
import { carryWake, takeWake } from './tabs-motion/carry';
import { TAB_KIND } from './rects/pending';
import { activeTabFor, mergeComponent, placeTab, splitTabOut } from './tab-groups.svelte';
import { viewport } from './viewport.svelte';
import { MAX_VIEWERS, PRIMARY_SLOT } from './model';
import { limitLine } from './components-actions';
import { inputFocus } from '../lib/input-focus.svelte';
import { primarySessionId } from '../api/host';
import { sessions } from '../api';
import { asleep, wakeOrPick } from '../api/asleep.svelte';
import { slotForSession } from './slot-identity';
import { t } from '../../lib/i18n/index.svelte';
import { splitThrough } from '../layouts/transition.svelte';
import { primaryRowId } from '../layouts/names';
import { isLayoutKey } from './session-layouts';
import { pageIdOfTab, pageTabOfRowName } from './page-tabs';
import { pageTabItem } from '../cells/terminal-group/page-tab-item';

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
  | { kind: 'middle'; slot: string }
  | { kind: 'out'; target: DropTarget };

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

export function swallowNextClick(): void {
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

export function commitTabDrop(tab: string, drop: TabDrop): boolean {
  const button = [...document.querySelectorAll<HTMLElement>(`#${GRID_ID} [data-tab]`)].find(
    (el) => el.dataset['tab'] === tab,
  );
  const pageId = pageIdOfTab(tab);
  const name = button?.title || (pageId === null ? tab : pageTabItem(tab, pageId).name);
  let line: string;
  if (drop.kind === 'strip' || drop.kind === 'middle') {
    const done = placeTab(terminalLayout, drop.slot, tab, drop.kind === 'strip' ? drop.index : Number.MAX_SAFE_INTEGER);
    if (!done) return false;
    line = t(done === 'added' ? 'opscenter.tabs.added' : 'opscenter.tabs.moved', { name });
  } else {
    const target = drop.target;
    const result = splitThrough(() => splitTabOut(terminalLayout, tab, target), (done) => done === 'split', null);
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

export function splitNeedsRow(): boolean {
  const key = terminalLayout.session;
  return terminalLayout.page === 'terminal' && !!key && !isLayoutKey(key) && primaryRowId() === null;
}

export function commitMerge(store: LayoutStore, from: string, into: string, index?: number): boolean {
  const done = mergeComponent(store, from, into, index);
  if (!done) return false;
  store.announce(t(done === 'merged' ? 'opscenter.tabs.merged' : 'opscenter.tabs.merge_primary'));
  if (done !== 'merged') return false;
  const shown = activeTabFor(store, into);
  inputFocus.claim(shown);
  void tick().then(() => focusTab(shown));
  return true;
}

export function componentMerge(id: string): CellDragMerge {
  void id;
  return { aim: () => false, drop: () => false, end: () => undefined };
}

/* there is nothing */
export function beginTabDrag(handle: HTMLElement, event: PointerEvent, tab: string): boolean {
  if (!viewport.wide || event.pointerType === 'touch') return false;
  return stripOf(handle)?.press(handle, event, tab) ?? false;
}

export function carryTab(tab: string, event: PointerEvent, wake?: () => void): boolean {
  const host = dropHostById('terminal');
  if (!host) return false;
  if (wake) carryWake(tab, wake);
  const taken = host.accept(TAB_KIND + tab, event);
  if (!taken) takeWake(tab);
  return taken;
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
  if (pageTab !== null) return carryTab(pageTab, pointerOf(start));
  const id = (sessions.data ?? []).find((row) => row.tmux_session === start.name)?.session?.id;
  if (!id) return beginAsleepTabDrag(start);
  const tab = id === primarySessionId() ? PRIMARY_SLOT : slotForSession(id, sessions.data);
  return carryTab(tab, pointerOf(start));
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
  return carryTab(`terminal:row:${rec.id}`, event, wake);
}
