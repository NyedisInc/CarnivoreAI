import { describe, expect, test, vi } from 'vitest';
import { createTabRegistry, refusalOf } from './registry';
import { TabController } from './tab-store.svelte';
import type { Component } from 'svelte';
import type { DynamicTabDef } from './types';

const Body = (() => {}) as unknown as Component;

function def(over: Partial<DynamicTabDef> & { id: string; order: number }): DynamicTabDef {
  return { labelKey: `t.${over.id}`, icon: 'grid', persist: false, widgetArea: 'full', body: { containers: [`c-${over.id}`] }, ...over };
}

function memory(): { getItem(k: string): string | null; setItem(k: string, v: string): void; data: Record<string, string> } {
  const data: Record<string, string> = {};
  return { data, getItem: (k) => data[k] ?? null, setItem: (k, v) => void (data[k] = v) };
}

describe('registering', () => {
  test('a tab is accepted and listed in order, whatever order it was registered in', () => {
    const r = createTabRegistry();
    expect(r.register(def({ id: 'b', order: 20 }))).toBeNull();
    expect(r.register(def({ id: 'a', order: 10 }))).toBeNull();
    expect(r.all().map((d) => d.id)).toEqual(['a', 'b']);
    expect(r.get('b')?.order).toBe(20);
    expect(r.get('missing')).toBeNull();
  });

  test('each broken field is refused by name and the tab is not half registered', () => {
    vi.spyOn(console, 'warn').mockImplementation(() => {});
    const r = createTabRegistry();
    r.register(def({ id: 'a', order: 10 }));
    expect(r.register(def({ id: 'Bad Id', order: 11 }))).toBe('id');
    expect(r.register(def({ id: 'a', order: 12 }))).toBe('duplicate-id');
    expect(r.register(def({ id: 'c', order: 10 }))).toBe('duplicate-order');
    expect(r.register(def({ id: 'd', order: Number.NaN }))).toBe('order');
    expect(r.register(def({ id: 'e', order: 13, labelKey: '' }))).toBe('label-key');
    expect(r.register(def({ id: 'f', order: 14, icon: '' }))).toBe('icon');
    expect(r.register(def({ id: 'g', order: 15, body: { containers: [] } }))).toBe('body');
    expect(r.register(def({ id: 'h', order: 16, widgetArea: 'huge' as never }))).toBe('widget-area');
    expect(r.all().map((d) => d.id)).toEqual(['a']);
    expect(refusalOf(def({ id: 'ok', order: 1, body: { component: Body } }), [])).toBeNull();
  });
});

describe('the lifecycle', () => {
  function setup() {
    const r = createTabRegistry();
    const state = { present: false };
    const opened = vi.fn(() => { state.present = true; return true; });
    const closed = vi.fn(() => { state.present = false; });
    r.register(def({ id: 'menu', order: 10, persist: true }));
    r.register(def({ id: 'agents', order: 20, persist: true }));
    r.register(def({ id: 'q', order: 30, present: () => state.present }));
    r.register(def({ id: 'edit', order: 40, present: () => state.present, focusOnAppear: true, open: opened, close: closed }));
    const store = memory();
    const c = new TabController(r, () => store);
    return { r, c, state, opened, closed, store };
  }

  test('a place is stored per device; a transient tab shows over it and never is stored', () => {
    const { c, state, store } = setup();
    expect(c.active()).toBe('agents');
    expect(c.select('menu')).toBe(true);
    expect(store.data['carnivore.session.sidebar.tab']).toBe('menu');
    expect(c.select('q'), 'an absent tab cannot be selected').toBe(false);
    state.present = true;
    expect(c.select('q')).toBe(true);
    expect(c.active()).toBe('q');
    expect(store.data['carnivore.session.sidebar.tab']).toBe('menu');
    c.leave();
    expect(c.active()).toBe('menu');
    expect(c.places().map((d) => d.id)).toEqual(['menu', 'agents']);
  });

  test('open makes the tab present through its own open, then shows it', () => {
    const { c, opened } = setup();
    expect(c.open('edit')).toBe(true);
    expect(opened).toHaveBeenCalledOnce();
    expect(c.active()).toBe('edit');
  });

  test('close calls the tab\'s own close and the stored place shows again; a tab without close is not closable', () => {
    const { c, closed, state } = setup();
    c.open('edit');
    c.close('edit');
    expect(closed).toHaveBeenCalledOnce();
    expect(c.active()).toBe('agents');
    state.present = true;
    c.select('q');
    c.close('q');
    expect(c.active(), 'q has no close: still showing').toBe('q');
  });

  test('AUTO-OPEN: a focusOnAppear tab that appears becomes active and runs onAppear once; a plain one waits', () => {
    const r = createTabRegistry();
    let on = false;
    const appeared = vi.fn();
    r.register(def({ id: 'agents', order: 20, persist: true }));
    r.register(def({ id: 'quiet', order: 30, present: () => on }));
    r.register(def({ id: 'loud', order: 40, present: () => on, focusOnAppear: true, onAppear: appeared }));
    const c = new TabController(r, () => null);
    c.noteAppearances(c.present().map((d) => d.id));
    expect(c.active()).toBe('agents');
    on = true;
    c.noteAppearances(c.present().map((d) => d.id));
    expect(c.active()).toBe('loud');
    expect(appeared).toHaveBeenCalledOnce();
    c.noteAppearances(c.present().map((d) => d.id));
    expect(appeared, 'still present: no second appearance').toHaveBeenCalledOnce();
  });

  test('AUTO-CLOSE: a transient tab that goes away leaves the strip and the stored place shows; it does not come back on its own', () => {
    const { c, state } = setup();
    state.present = true;
    c.noteAppearances(c.present().map((d) => d.id));
    c.select('q');
    state.present = false;
    expect(c.active()).toBe('agents');
    c.noteAppearances(c.present().map((d) => d.id));
    expect(c.transient).toBeNull();
    expect(c.present().map((d) => d.id)).toEqual(['menu', 'agents']);
  });

  test('reload: only a registered persist tab is a stored place', () => {
    const { c, store } = setup();
    store.data['carnivore.session.sidebar.tab'] = 'q';
    c.reload();
    expect(c.stored).toBe('agents');
    store.data['carnivore.session.sidebar.tab'] = 'menu';
    c.reload();
    expect(c.stored).toBe('menu');
  });
});
