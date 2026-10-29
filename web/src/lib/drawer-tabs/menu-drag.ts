import { t } from '../i18n/index.svelte';
import { announce } from '../sidebar-shell/interaction-globals';
import { slop } from '../sidebar-shell/row-drag';
import { moveBefore } from './menu-order.svelte';

export const LONG_PRESS_MS = 350;

const ROW_ATTR = 'data-menu-row';
const LIFTED_ATTR = 'data-menu-lifted';
const DROP_ATTR = 'data-menu-drop';

export interface MenuDragHost {
  ids(): string[];
  commit(ids: string[]): void;
  marker?: string;
}

interface Drag {
  id: string;
  li: HTMLElement;
  list: HTMLElement;
  zones: HTMLElement[];
  host: MenuDragHost;
  startX: number;
  startY: number;
  pointerId: number;
  pointerType: string;
  active: boolean;
  timer: ReturnType<typeof setTimeout> | null;
  before: string | null | undefined;
}

let drag: Drag | null = null;

function rowName(li: HTMLElement, fallback: string): string {
  return li.querySelector('.oc-nav-label')?.textContent?.trim() || fallback;
}

function lines(list: HTMLElement): HTMLElement[] {
  return Array.from(list.querySelectorAll<HTMLElement>(`:scope > li[${ROW_ATTR}]`));
}

function beforeAt(list: HTMLElement, clientY: number): string | null {
  for (const li of lines(list)) {
    const r = li.getBoundingClientRect();
    if (clientY < r.top + r.height / 2) return li.getAttribute(ROW_ATTR);
  }
  return null;
}

function paintDrop(zones: HTMLElement[], list: HTMLElement, before: string | null): void {
  clearDrop(zones);
  const all = lines(list);
  const target = before === null ? all[all.length - 1] : all.find((li) => li.getAttribute(ROW_ATTR) === before);
  (target ?? list).setAttribute(DROP_ATTR, before === null ? 'after' : 'before');
}

function clearDrop(zones: HTMLElement[]): void {
  for (const zone of zones) {
    zone.removeAttribute(DROP_ATTR);
    zone.querySelectorAll(`[${DROP_ATTR}]`).forEach((el) => el.removeAttribute(DROP_ATTR));
  }
}

function pickZone(zones: HTMLElement[], clientY: number): HTMLElement {
  let best = zones[0] as HTMLElement;
  let gap = Infinity;
  for (const zone of zones) {
    const r = zone.getBoundingClientRect();
    const away = clientY < r.top ? r.top - clientY : clientY > r.bottom ? clientY - r.bottom : 0;
    if (away < gap) {
      gap = away;
      best = zone;
    }
  }
  return best;
}

function swallowClick(): void {
  const eat = (ev: Event): void => { ev.stopPropagation(); ev.preventDefault(); };
  window.addEventListener('click', eat, { capture: true, once: true });
  setTimeout(() => window.removeEventListener('click', eat, true), 0);
}

function blockScroll(ev: TouchEvent): void {
  if (drag?.active && ev.cancelable) ev.preventDefault();
}

function lift(d: Drag): void {
  d.active = true;
  d.li.setAttribute(LIFTED_ATTR, '1');
  d.list.style.cursor = 'grabbing';
}

function positionSentence(host: MenuDragHost, next: readonly string[], id: string, name: string): string {
  const rows = host.marker ? next.filter((x) => x !== host.marker) : next;
  return t('sidebar.row.move.moved', { name, position: rows.indexOf(id) + 1, total: rows.length });
}

function finish(drop: boolean): void {
  const d = drag;
  if (!d) return;
  drag = null;
  if (d.timer) clearTimeout(d.timer);
  document.removeEventListener('pointermove', onMove);
  document.removeEventListener('pointerup', onUp);
  document.removeEventListener('pointercancel', onCancel);
  document.removeEventListener('keydown', onEscape, true);
  document.removeEventListener('touchmove', blockScroll);
  d.li.removeAttribute(LIFTED_ATTR);
  d.list.style.cursor = '';
  clearDrop(d.zones);
  if (!d.active) return;
  swallowClick();
  if (!drop || d.before === undefined) return;
  const ids = d.host.ids();
  const next = moveBefore(ids, d.id, d.before ?? d.list.dataset.menuEnd ?? null);
  if (next.some((id, i) => id !== ids[i])) {
    d.host.commit(next);
    announce(positionSentence(d.host, next, d.id, rowName(d.li, d.id)));
  }
}

function onMove(e: PointerEvent): void {
  const d = drag;
  if (!d || e.pointerId !== d.pointerId) return;
  if (!d.active) {
    const far = Math.hypot(e.clientX - d.startX, e.clientY - d.startY) > slop(d.pointerType);
    if (!far) return;
    if (d.pointerType === 'touch') return finish(false);
    lift(d);
  }
  e.preventDefault();
  const list = d.zones.length > 1 ? pickZone(d.zones, e.clientY) : d.list;
  const before = beforeAt(list, e.clientY);
  if (before !== d.before || list !== d.list) {
    d.list = list;
    d.before = before;
    paintDrop(d.zones, list, before);
  }
}

function onUp(e: PointerEvent): void {
  if (drag && e.pointerId === drag.pointerId) finish(true);
}

function onCancel(e: PointerEvent): void {
  if (drag && e.pointerId === drag.pointerId) finish(false);
}

function onEscape(e: KeyboardEvent): void {
  if (drag && e.key === 'Escape') {
    e.stopPropagation();
    finish(false);
  }
}

function zonesOf(list: HTMLElement): HTMLElement[] {
  const root = list.closest<HTMLElement>('[data-menu-zones]');
  const all = root ? Array.from(root.querySelectorAll<HTMLElement>('[data-menu-zone]')) : [];
  return all.length > 0 ? all : [list];
}

export function onMenuPointerDown(e: PointerEvent, host: MenuDragHost): void {
  if (drag || (typeof e.button === 'number' && e.button !== 0)) return;
  const target = e.target as Element | null;
  const li = target?.closest<HTMLElement>(`li[${ROW_ATTR}]`) ?? null;
  const list = li?.parentElement ?? null;
  if (!li || !list || target?.closest('[data-menu-popout], [data-menu-dashboards-caret], [data-menu-nodrag]')) return;
  const id = li.getAttribute(ROW_ATTR) as string;
  const d: Drag = {
    id, li, list, zones: zonesOf(list), host, startX: e.clientX, startY: e.clientY, pointerId: e.pointerId, pointerType: e.pointerType,
    active: false, timer: null, before: undefined,
  };
  drag = d;
  if (e.pointerType === 'touch') {
    d.timer = setTimeout(() => {
      if (drag === d) {
        lift(d);
        try { navigator.vibrate?.(8); } catch {  }
      }
    }, LONG_PRESS_MS);
  }
  document.addEventListener('pointermove', onMove);
  document.addEventListener('pointerup', onUp);
  document.addEventListener('pointercancel', onCancel);
  document.addEventListener('keydown', onEscape, true);
  document.addEventListener('touchmove', blockScroll, { passive: false });
}

export function onMenuMoveKey(e: KeyboardEvent, host: MenuDragHost): boolean {
  if (!e.altKey || (e.key !== 'ArrowUp' && e.key !== 'ArrowDown')) return false;
  const li = (e.target as Element | null)?.closest<HTMLElement>(`li[${ROW_ATTR}]`);
  if (!li) return false;
  e.preventDefault();
  const id = li.getAttribute(ROW_ATTR) as string;
  const ids = host.ids();
  const at = ids.indexOf(id);
  const to = at + (e.key === 'ArrowDown' ? 1 : -1);
  const name = rowName(li, id);
  if (at === -1 || to < 0 || to >= ids.length) {
    announce(t(to < 0 ? 'sidebar.row.move.top_of_list' : 'sidebar.row.move.bottom_of_list', { name }));
    return true;
  }
  const next = moveBefore(ids, id, e.key === 'ArrowDown' ? (ids[to + 1] ?? null) : (ids[to] as string));
  host.commit(next);
  announce(positionSentence(host, next, id, name));
  queueMicrotask(() => li.querySelector<HTMLElement>('.oc-nav-item')?.focus());
  return true;
}
