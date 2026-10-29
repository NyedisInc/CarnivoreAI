import { expect } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';
import SessionRail from './SessionRail.svelte';
import { RAIL_FIELD, RAIL_SPECS, type RailEdge } from './rail-model';
import { OUT_DEFAULT_PX } from './rail-size';
import { railStores } from './rail-store.svelte';
import { railSlideout } from './slideout.svelte';
import { lastUsedKey, openKey } from './rail-open';
import { layoutEditor } from '../../opscenter/layout-editor/editor.svelte';

const HIDDEN_ICONS_FIELD = 'rail_hidden_icons';
export const BOTTOM_FIELD = RAIL_SPECS.bottom.field;

/* the bottom rail */
export const RAIL_BOX: Readonly<Record<RailEdge, { left: number; top: number; width: number; height: number }>> = {
  side: { left: 1000, top: 0, width: 36, height: 400 },
  bottom: { left: 0, top: 700, width: 900, height: 36 },
};

export const written: { field: string; value: unknown }[] = [];

export const batches: string[][] = [];

const followers: Record<string, (value: unknown) => void> = {};
let hosts: HTMLElement[] = [];
let instances: unknown[] = [];

export function ptr(type: string, x: number, y: number): PointerEvent {
  const event = new MouseEvent(type, { clientX: x, clientY: y, bubbles: true, button: 0 }) as PointerEvent;
  Object.defineProperty(event, 'pointerId', { value: 1 });
  Object.defineProperty(event, 'pointerType', { value: 'mouse' });
  return event;
}

export function box(left: number, top: number, width: number, height: number): DOMRect {
  return { left, top, width, height, right: left + width, bottom: top + height, x: left, y: top, toJSON: () => ({}) };
}

export function layOutRail(edge: RailEdge): void {
  const rail = document.getElementById(RAIL_SPECS[edge].id);
  if (!rail) return;
  const b = RAIL_BOX[edge];
  const side = edge === 'side';
  rail.getBoundingClientRect = () => box(b.left, b.top, b.width, b.height);
  const length = side ? b.height : b.width;
  const sections = [...rail.querySelectorAll<HTMLElement>('[data-rail-section]')];
  const cut = railStores[edge].ratio * length;
  sections.forEach((section, s) => {
    const start = sections.length < 2 || s === 0 ? 0 : cut;
    const end = sections.length < 2 || s === 1 ? length : cut;
    section.getBoundingClientRect = () => (side ? box(b.left, b.top + start, b.width, end - start) : box(b.left + start, b.top, end - start, b.height));
    section.querySelectorAll<HTMLElement>('[data-zone-item]').forEach((key, i) => {
      key.getBoundingClientRect = () => (side ? box(b.left + 4, b.top + start + 10 + i * 32, 28, 28) : box(b.left + start + 10 + i * 32, b.top + 4, 28, 28));
    });
  });
  const out = OUT_DEFAULT_PX[edge];
  rail.querySelectorAll<HTMLElement>('[data-rail-band]').forEach((band) => {
    const first = band.dataset['railBand'] === 'start';
    band.getBoundingClientRect = () =>
      side
        ? box(b.left - out, first ? b.top : b.top + length * 0.7, out, length * 0.3)
        : box(first ? b.left : b.left + length * 0.7, b.top - out, length * 0.3, out);
  });
}

export function layOutRails(): void {
  layOutRail('side');
  layOutRail('bottom');
}

export function keysIn(edge: RailEdge): string[] {
  return [...document.querySelectorAll<HTMLElement>(`#${RAIL_SPECS[edge].id} [data-zone-item]`)].map((k) => k.dataset['zoneItem']!);
}

export function sectionKeysIn(edge: RailEdge): string[][] {
  return [...document.querySelectorAll<HTMLElement>(`#${RAIL_SPECS[edge].id} [data-rail-section]`)].map((section) =>
    [...section.querySelectorAll<HTMLElement>('[data-zone-item]')].map((k) => k.dataset['zoneItem']!));
}

export function keyIn(edge: RailEdge, id: string): HTMLElement {
  return document.querySelector<HTMLElement>(`#${RAIL_SPECS[edge].id} [data-zone-item="${id}"]`)!;
}

export const AUTOHIDE_BARS = Object.freeze({ v: 1, side: { mode: 'autohide' }, bottom: { mode: 'autohide' } });

export function follow(field: string, value: unknown): void {
  followers[field]!(field === 'widget_bars' && value === null ? AUTOHIDE_BARS : value);
  flushSync();
}

export function mountRails(): void {
  (globalThis as { ResizeObserver?: unknown }).ResizeObserver = class {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
  };
  (Element.prototype as { animate?: unknown }).animate = function animate() {
    const animation = { onfinish: null as null | (() => void), cancel() {}, play() {}, pause() {}, currentTime: 0, finished: Promise.resolve() };
    setTimeout(() => animation.onfinish?.(), 0);
    return animation;
  };
  written.length = 0;
  batches.length = 0;
  railStores.side.stored = null;
  railStores.bottom.stored = null;
  for (const edge of ['side', 'bottom'] as const) { localStorage.removeItem(lastUsedKey(edge)); localStorage.removeItem(openKey(edge)); }
  railSlideout.reload();
  railSlideout.close();
  layoutEditor.active = false;
  (globalThis as { PreferenceBridge?: unknown }).PreferenceBridge = {
    read: () => null,
    write: async (field: string, value: unknown) => {
      expect([RAIL_FIELD, BOTTOM_FIELD, HIDDEN_ICONS_FIELD]).toContain(field);
      written.push({ field, value });
      batches.push([field]);
      return { status: 'committed' };
    },
    writeMany: async (entries: { field: string; value: unknown }[]) => {
      for (const { field, value } of entries) {
        expect([RAIL_FIELD, BOTTOM_FIELD, HIDDEN_ICONS_FIELD]).toContain(field);
        written.push({ field, value });
      }
      batches.push(entries.map((entry) => entry.field));
      return { status: 'committed' };
    },
    follow: (field: string, apply: (value: unknown) => void) => {
      followers[field] ??= apply;
      return () => {};
    },
  };
  remountRails();
  followers['widget_bars']?.(AUTOHIDE_BARS);
  flushSync();
}

export function remountRails(): void {
  for (const edge of ['side', 'bottom'] as const) {
    const host = document.createElement('div');
    document.body.appendChild(host);
    hosts.push(host);
    instances.push(mount(SessionRail, { target: host, props: { edge } }));
  }
  flushSync();
}

export function unmountRails(): void {
  for (const one of instances) void unmount(one as Record<string, unknown>);
  for (const host of hosts) host.remove();
  hosts = [];
  instances = [];
  layoutEditor.active = false;
}
