import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { bindState, initialValue, readStored, rememberedNames, stateKey, type StateSpec } from './widget-state.svelte';

const isBool = (value: unknown): value is boolean => typeof value === 'boolean';
const isMode = (value: unknown): value is 'edit' | 'preview' => value === 'edit' || value === 'preview';

let map: Map<string, string>;
let writes: string[];

function installStorage(refuse = false): void {
  const guard = (): void => {
    if (refuse) throw new Error('storage refused');
  };
  vi.stubGlobal('localStorage', {
    getItem: (key: string): string | null => (guard(), map.get(key) ?? null),
    setItem: (key: string, value: string): void => {
      guard();
      writes.push(key);
      map.set(key, value);
    },
    removeItem: (key: string): void => void map.delete(key),
  });
}

beforeEach(() => {
  map = new Map();
  writes = [];
  installStorage();
  vi.spyOn(console, 'warn').mockImplementation(() => {});
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe('keys and names', () => {
  test('device and placement keys', () => {
    expect(stateKey('core.notes', 'mode')).toBe('carnivore.core.notes.mode');
    expect(stateKey('core.files', 'show-path', 'rail:left:3')).toBe('carnivore.core.files.rail:left:3.show-path');
  });

  test('rememberedNames is the declaration order, [] for a stateless widget', () => {
    const spec: StateSpec = { mode: { home: 'device', default: 'edit', valid: isMode }, folds: { home: 'device', default: false, valid: isBool } };
    expect(rememberedNames(spec)).toEqual(['mode', 'folds']);
    expect(rememberedNames({})).toEqual([]);
  });
});

describe('reading', () => {
  test('an invalid or malformed stored value reads as the default, and the default is not written', () => {
    map.set('carnivore.core.notes.mode', 'sideways');
    const state = bindState('core.notes', { mode: { home: 'device', default: 'edit', valid: isMode } }, () => '');
    expect(state.mode).toBe('edit');
    expect(writes).toEqual([]);
  });

  test('a string is read raw and anything else as JSON', () => {
    map.set('carnivore.probe.flag', 'true');
    map.set('carnivore.probe.mode', 'preview');
    expect(readStored('carnivore.probe.flag')).toEqual([true, 'true']);
    expect(initialValue({ home: 'device', default: false, valid: isBool }, 'carnivore.probe.flag')).toBe(true);
    expect(initialValue({ home: 'device', default: 'edit', valid: isMode }, 'carnivore.probe.mode')).toBe('preview');
  });

  test('the legacy key is read when the new key holds nothing, and the new key wins when it holds a value', () => {
    map.set('cloude_notes_preview', 'preview');
    const field = { home: 'device', default: 'edit', valid: isMode, legacyKey: 'cloude_notes_preview' } as const;
    expect(initialValue(field, 'carnivore.core.notes.mode')).toBe('preview');
    map.set('carnivore.core.notes.mode', 'edit');
    expect(initialValue(field, 'carnivore.core.notes.mode')).toBe('edit');
  });
});

describe('writing', () => {
  test('an owner change writes; an invalid one is refused', () => {
    const state = bindState('core.notes', { mode: { home: 'device', default: 'edit', valid: isMode } }, () => '');
    state.mode = 'preview';
    expect(state.mode).toBe('preview');
    expect(map.get('carnivore.core.notes.mode')).toBe('preview');
    (state as { mode: unknown }).mode = 'sideways';
    expect(state.mode).toBe('preview');
  });

  test('a placement field keys on the copy, so two copies never share', () => {
    const spec = { open: { home: 'placement', default: false, valid: isBool } } as const;
    const one = bindState('core.files', spec, () => 'slot-a');
    const two = bindState('core.files', spec, () => 'slot-b');
    one.open = true;
    expect(map.get('carnivore.core.files.slot-a.open')).toBe('true');
    expect(two.open).toBe(false);
    expect(map.has('carnivore.core.files.open')).toBe(false);
  });

  test('a placement field with no copy id is held in memory and never written', () => {
    const state = bindState('core.files', { open: { home: 'placement', default: false, valid: isBool } }, () => '');
    state.open = true;
    expect(state.open).toBe(true);
    expect(writes).toEqual([]);
  });

  test('a storage that throws leaves the widget correct in memory', () => {
    installStorage(true);
    const state = bindState('core.notes', { mode: { home: 'device', default: 'edit', valid: isMode } }, () => '');
    expect(state.mode).toBe('edit');
    state.mode = 'preview';
    expect(state.mode).toBe('preview');
  });

  test('a shared field reads and writes through its accessor, and adds no stored key', () => {
    let held: unknown = 'bogus';
    const via = { read: () => held, write: (value: boolean) => void (held = value) };
    const state = bindState('core.tasks', { folds: { home: 'shared', default: false, valid: isBool, via } }, () => '');
    expect(state.folds).toBe(false);
    state.folds = true;
    expect(held).toBe(true);
    expect(writes).toEqual([]);
  });
});
