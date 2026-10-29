import { describe, expect, test, vi } from 'vitest';
import './builtin';
import { tabRegistry } from './registry';
import { WIDGET_AREA_STORAGE_KEY, WidgetAreaStore, readAreaOverrides, snapAreaState, stepAreaState } from './widget-area.svelte';
import { WIDGET_AREA_STATES } from './types';

function memory(seed: Record<string, string> = {}) {
  const data: Record<string, string> = { ...seed };
  return { data, getItem: (k: string) => data[k] ?? null, setItem: (k: string, v: string) => void (data[k] = v) };
}

describe('defaults', () => {
  test('each shipped tab opens the area in its own default state', () => {
    const area = new WidgetAreaStore(tabRegistry, () => memory());
    expect(WIDGET_AREA_STATES).toEqual(['closed', 'glance', 'full']);
    expect(area.stateFor('agents')).toBe('full');
    expect(area.stateFor('menu')).toBe('glance');
    expect(area.stateFor('questions')).toBe('glance');
    expect(area.stateFor('edit-layout')).toBe('full');
    expect(area.stateFor('nobody'), 'an unknown tab').toBe('full');
  });
});

describe('persistence', () => {
  test('a change is per tab and survives a reload on this device; only states are stored, never a size', () => {
    const store = memory();
    const area = new WidgetAreaStore(tabRegistry, () => store);
    area.set('menu', 'full');
    expect(area.toggle('agents')).toBe('closed');
    expect(JSON.parse(store.data[WIDGET_AREA_STORAGE_KEY] ?? '{}')).toEqual({ menu: 'full', agents: 'closed' });
    const again = new WidgetAreaStore(tabRegistry, () => store);
    expect(again.stateFor('menu')).toBe('full');
    expect(again.stateFor('agents')).toBe('closed');
    expect(again.stateFor('questions'), 'untouched tabs keep their default').toBe('glance');
    expect(again.toggle('questions'), 'glance opens full').toBe('full');
  });

  test('malformed or unreadable storage falls back to the defaults, and a refused write keeps the state for the page', () => {
    vi.spyOn(console, 'warn').mockImplementation(() => {});
    expect(readAreaOverrides(memory({ [WIDGET_AREA_STORAGE_KEY]: '{not json' }))).toEqual({});
    expect(readAreaOverrides(memory({ [WIDGET_AREA_STORAGE_KEY]: '{"menu":"huge","agents":"glance"}' }))).toEqual({ agents: 'glance' });
    expect(readAreaOverrides({ getItem: () => { throw new Error('blocked'); }, setItem: () => {} })).toEqual({});
    const area = new WidgetAreaStore(tabRegistry, () => ({ getItem: () => null, setItem: () => { throw new Error('full'); } }));
    area.set('menu', 'closed');
    expect(area.stateFor('menu')).toBe('closed');
  });
});

describe('the rename', () => {
  test('a state stored before 2026-10-02 (open, mini) reads as full and glance', () => {
    expect(readAreaOverrides(memory({ [WIDGET_AREA_STORAGE_KEY]: '{"menu":"open","agents":"mini","questions":"closed"}' }))).toEqual({
      menu: 'full',
      agents: 'glance',
      questions: 'closed',
    });
  });
});

describe('snapping and stepping', () => {
  test('a drag lands on the state whose height is nearest, never between', () => {
    const glance = 40;
    const full = 200;
    expect(snapAreaState(0, glance, full)).toBe('closed');
    expect(snapAreaState(19, glance, full)).toBe('closed');
    expect(snapAreaState(20, glance, full), 'a tie goes to the larger').toBe('glance');
    expect(snapAreaState(110, glance, full)).toBe('glance');
    expect(snapAreaState(121, glance, full)).toBe('full');
    expect(snapAreaState(900, glance, full)).toBe('full');
    expect(snapAreaState(-50, glance, full)).toBe('closed');
    expect(snapAreaState(45, glance, 10), 'a full shorter than glance still sits above it').toBe('full');
  });

  test('the keys step one state and stop at the ends', () => {
    expect(stepAreaState('closed', 1)).toBe('glance');
    expect(stepAreaState('glance', 1)).toBe('full');
    expect(stepAreaState('full', 1)).toBe('full');
    expect(stepAreaState('full', -1)).toBe('glance');
    expect(stepAreaState('closed', -1)).toBe('closed');
  });
});
