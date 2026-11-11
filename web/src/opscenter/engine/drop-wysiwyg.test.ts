/** @vitest-environment jsdom */
import { afterEach, beforeEach, expect, test } from 'vitest';
import type { GestureState, Rect, Source } from '../../lib/motion-grid';
import { t } from '../../lib/i18n/index.svelte';
import { terminalLayout } from './layout.svelte';
import { componentMerge } from './tab-drag';
import { resetTabCache, setGroups, tabsFor } from './tab-groups.svelte';
import { PRIMARY_SLOT } from './model';
import { pendingForTab, type Pending } from './rects/pending';
import { createRowsAdapter, DWELL_MS } from './rects/rows-adapter';
import { layoutGeometry } from './rects/layout-rects';
import type { Layout, RowModel, SlotId } from './types';

const S = (n: string) => `terminal:${n}` as SlotId;
const P = PRIMARY_SLOT as SlotId;
const W = 3300, H = 1250, G = 9, STRIP = 30;
const T1 = 'terminal:t1';
const layoutOf = (rows: RowModel[]): Layout => ({ v: 6, rows, hidden: [], heroCollapsed: false, collapsed: [] });

const working = (): Layout => layoutOf([
  { id: 'r1', kind: 'flex', size: 0.5, slots: [{ id: P, fr: 0.33 }, { id: S('b'), fr: 0.33 }, { id: S('c'), fr: 0.34, span: 2 }] } as RowModel,
  { id: 'r2', kind: 'flex', size: 0.5, slots: [{ id: S('d'), fr: 0.3 }, { id: S('e'), fr: 0.3 }, { id: S('g'), fr: 0.4 }], reserved: [{ of: S('c'), at: 3 }] } as RowModel,
]);

const unaligned = (): Layout => layoutOf([
  { id: 'r1', kind: 'flex', size: 0.34, slots: [{ id: P, fr: 0.2 }, { id: S('g'), fr: 0.8 }] } as RowModel,
  { id: 'r2', kind: 'flex', size: 0.33, slots: [{ id: S('c'), fr: 0.4 }, { id: S('d'), fr: 0.6 }] } as RowModel,
  { id: 'r3', kind: 'flex', size: 0.33, slots: [{ id: S('f'), fr: 0.4 }, { id: S('h'), fr: 0.6 }] } as RowModel,
]);

const near = (a: Rect | undefined, b: Rect | undefined, by = 1): boolean =>
  !!a && !!b && Math.abs(a.x - b.x) <= by && Math.abs(a.y - b.y) <= by && Math.abs(a.w - b.w) <= by && Math.abs(a.h - b.h) <= by;
const rectsOf = (layout: Layout) => layoutGeometry(layout, W, H, G).rects;

function load(layout: Layout): void {
  (terminalLayout.state as { layout: Layout }).layout = structuredClone(layout);
  const slots = layout.rows.flatMap((row) => row.slots.map((slot) => slot.id as string));
  setGroups(terminalLayout, Object.fromEntries(slots.map((slot) => [slot, { tabs: slot === P ? [P, T1] : [slot] }])));
}

function container(layout: Layout): HTMLElement {
  const root = document.createElement('div');
  root.getBoundingClientRect = () => ({ left: 0, top: 0, right: W, bottom: H, width: W, height: H }) as DOMRect;
  for (const [slot, r] of rectsOf(layout)) {
    const group = document.createElement('div');
    group.dataset['tabGroup'] = slot;
    const tabs = tabsFor(terminalLayout, slot);
    tabs.forEach((tab, i) => {
      const b = document.createElement('button');
      b.dataset['tab'] = tab;
      b.getBoundingClientRect = () => ({ left: r.x + 10 + i * 100, right: r.x + 90 + i * 100, top: r.y, bottom: r.y + STRIP, width: 80, height: STRIP }) as DOMRect;
      group.appendChild(b);
    });
    group.getBoundingClientRect = () => ({ left: r.x, right: r.x + r.w, top: r.y, bottom: r.y + STRIP, width: r.w, height: STRIP }) as DOMRect;
    root.appendChild(group);
  }
  document.body.appendChild(root);
  return root;
}

type Kind = 'tab' | 'window' | 'only-tab';

const pendingOf = (kind: Kind): Pending | null =>
  kind === 'tab' ? pendingForTab(terminalLayout, T1) : kind === 'only-tab' ? pendingForTab(terminalLayout, S('g')) : null;

function drag(layout: Layout, kind: Kind, made?: Pending | null) {
  load(layout);
  const clock = { t: 1000 };
  const root = container(layout);
  const adapter = createRowsAdapter({
    store: terminalLayout, box: () => ({ width: W, height: H }), gutter: G, wide: () => true, zoomed: () => null,
    container: () => root, merge: (id) => (id.startsWith('terminal:') ? componentMerge(id) : undefined), onState: () => {}, now: () => clock.t,
  });
  const pending = made !== undefined ? made : pendingOf(kind);
  if (kind !== 'window') expect(pending, kind).not.toBeNull();
  const source: Source = kind === 'tab' ? { kind: 'external', id: '@ghost' } : { kind: 'move', id: S('g') };
  const active = kind === 'tab' ? pending!.id : S('g');
  const at = (x: number, y: number): GestureState => ({
    source, pointer: { x, y }, start: { x: 0, y: 0 }, delta: { x: 0, y: 0 }, grab: { x: 0, y: 0 },
    startRect: null, base: adapter.rects(), bounds: { w: W, h: H }, outside: false,
  });
  return {
    adapter, at, active, pending, source, clock,
    begin: () => { if (pending) adapter.setPending(pending); adapter.begin!(source, kind === 'tab' ? 'external' : 'pointer'); },
  };
}

function points(layout: Layout): [number, number][] {
  const xs = new Set([-20, 5, 12, W - 12, W - 5, W + 20]);
  const ys = new Set([-20, 2, 5, H - 12, H - 5, H + 20]);
  for (const r of rectsOf(layout).values()) {
    for (const x of [r.x + 10, r.x + 30, r.x + r.w / 2, r.x + r.w - 30, r.x + r.w - 10, r.x + r.w + 4, r.x - 4]) xs.add(Math.round(x));
    for (const y of [r.y + 10, r.y + STRIP + 15, r.y + STRIP + 60, r.y + r.h / 2, r.y + r.h - 25, r.y + r.h - 10, r.y + r.h + 4, r.y - 4]) ys.add(Math.round(y));
  }
  const icons: [number, number][] = [];
  for (const r of rectsOf(layout).values()) {
    const cx = Math.round(r.x + r.w / 2);
    const cy = Math.round(r.y + STRIP + (r.h - STRIP) / 2);
    icons.push([cx, cy], [cx - 44, cy], [cx + 44, cy], [cx, cy - 44], [cx, cy + 44]);
  }
  return [...[...xs].flatMap((x) => [...ys].map((y): [number, number] => [x, y])), ...icons];
}

const LABELS = ['opscenter.tabs.drop_left', 'opscenter.tabs.drop_right', 'opscenter.tabs.drop_top', 'opscenter.tabs.drop_bottom',
  'opscenter.drop.column_left', 'opscenter.drop.column_right', 'opscenter.drop.row_top', 'opscenter.drop.row_bottom',
  'opscenter.drop.column', 'opscenter.drop.row'];

beforeEach(() => resetTabCache());
afterEach(() => {
  terminalLayout.resetAll();
  resetTabCache();
  localStorage.clear();
  document.body.innerHTML = '';
});

for (const [name, make] of [['Working', working], ['unaligned seams', unaligned]] as const) {
  for (const kind of ['tab', 'window', 'only-tab'] as const) {
    test(`${name}, ${kind} drag: the armed box and every window are exactly what the drop lands`, () => {
      const start = make();
      const labels = new Set<string>();
      const seen = new Set<string>();
      let landed = 0;
      load(start);
      const made = pendingOf(kind);
      for (const [x, y] of points(start)) {
        const d = drag(start, kind, made);
        d.begin();
        const point = d.at(x, y);
        const key = d.adapter.targetKey(point);
        if (key === 'none' || key === 'out' || seen.has(key)) { d.adapter.cancel(); continue; }
        seen.add(key);
        const idle = d.adapter.preview(point, key);
        const box = idle.landing;
        const where = `${name} ${kind} (${x},${y}) ${key}`;
        if (idle.mark) labels.add(idle.mark.label);
        const reflows = !key.startsWith('strip:') && !key.startsWith('mid:');
        if (box) expect(near(idle.rects.get(d.active), box), `${where} idle rect`).toBe(true);
        if (reflows) for (const [id, r] of rectsOf(start)) if (id !== S('g') && id !== d.active) expect(near(idle.rects.get(id), r), `${where} idle ${id}`).toBe(true);
        d.clock.t += DWELL_MS + 60;
        const armedKey = d.adapter.targetKey(point);
        const folds = !reflows && kind !== 'tab';
        expect(armedKey, where).toBe(reflows || folds ? `${key}|a` : key);
        const armed = d.adapter.preview(point, armedKey);
        d.adapter.commit(armed, point);
        const now = terminalLayout.state.layout;
        if (reflows) {
          landed += 1;
          const committed = rectsOf(now);
          expect(near(armed.landing ?? undefined, committed.get(d.active)), `${where} landing ${JSON.stringify(armed.landing)} vs ${JSON.stringify(committed.get(d.active))}`).toBe(true);
          for (const [id, r] of committed) if (id !== d.active) expect(near(armed.rects.get(id), r), `${where} armed ${id}`).toBe(true);
          expect(committed.size, where).toBe(rectsOf(start).size + (kind === 'tab' ? 1 : 0));
        } else {
          if (folds) for (const [id, r] of rectsOf(now)) expect(near(armed.rects.get(id), r), `${where} armed fold ${id}`).toBe(true);
        }
        if (!reflows && (kind === 'tab' || kind === 'only-tab')) {
          const into = key.split(':')[1] === undefined ? '' : key.replace(/^(strip|mid):/, '').replace(/:\d+$/, '');
          expect(tabsFor(terminalLayout, into), where).toContain(kind === 'tab' ? T1 : S('g'));
        }
        if (key.startsWith('mid:')) expect(armed.mark?.label, where).toBe(t(kind === 'window' ? 'opscenter.drop.add_tabs' : 'opscenter.tabs.drop_center'));
      }
      expect(landed).toBeGreaterThan(20);
      for (const label of LABELS) expect([...labels], `${name} ${kind} never aimed at ${label}`).toContain(t(label));
    }, 120_000);
  }
}

test('a quick release before the dwell lands exactly the box that was shown (the thumbnail flies there)', () => {
  const start = working();
  const d = drag(start, 'tab');
  d.begin();
  const b = rectsOf(start).get(S('b'))!;
  const point = d.at(b.x + b.w / 2 - 44, b.y + STRIP + (b.h - STRIP) / 2);
  const key = d.adapter.targetKey(point);
  expect(key).toBe(`split:${S('b')}:left`);
  const idle = d.adapter.preview(point, key);
  d.adapter.commit(idle, point);
  const committed = rectsOf(terminalLayout.state.layout);
  expect(near(idle.landing ?? undefined, committed.get(d.active))).toBe(true);
  expect(near(idle.rects.get(d.active), committed.get(d.active))).toBe(true);
});

test('a 3 px wobble inside a compass icon for 40 frames holds one target and never reflows after the arm', () => {
  for (const kind of ['tab', 'window'] as const) {
    const start = working();
    const d = drag(start, kind);
    d.begin();
    const b = rectsOf(start).get(S('b'))!;
    const line = b.x + b.w / 2 - 44;
    const keys: string[] = [];
    for (let i = 0; i < 40; i++) {
      d.clock.t += 16;
      keys.push(d.adapter.targetKey(d.at(line + (i % 2 ? 1.5 : -1.5), b.y + STRIP + (b.h - STRIP) / 2)).replace(/\|a$/, ''));
    }
    expect(new Set(keys).size, `${kind} ${[...new Set(keys)].join(' ')}`).toBe(1);
  }
});

test('nothing under the pointer: the ghost dims (invalid) and a release cancels', () => {
  const start = working();
  const d = drag(start, 'window');
  d.begin();
  const own = rectsOf(start).get(S('g'))!;
  const point = d.at(own.x + own.w / 2, own.y + own.h / 2);
  const target = d.adapter.preview(point, d.adapter.targetKey(point));
  expect(target.valid).toBe(false);
  expect(target.landing).toBeNull();
});
