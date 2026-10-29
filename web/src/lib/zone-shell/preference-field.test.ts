/** @vitest-environment jsdom */
import { afterEach, describe, expect, test, vi } from 'vitest';
import { DrawerZoneStore } from '../drawer-zone/zone-store.svelte';
import { RailStore } from '../session-rail/rail-layout-store.svelte';
import { PreferenceField } from './preference-field';

interface FakeBridge {
  value: unknown;
  writes: { field: string; value: unknown }[];
  listeners: ((value: unknown) => void)[];
  read: ReturnType<typeof vi.fn>;
  write: (field: string, value: unknown) => Promise<unknown>;
  writeMany: () => Promise<unknown>;
  follow: (field: string, apply: (value: unknown) => void) => () => void;
}

function install(initial: unknown): FakeBridge {
  const fake: FakeBridge = {
    value: initial,
    writes: [],
    listeners: [],
    read: vi.fn(() => fake.value),
    write: async (field, value) => {
      fake.writes.push({ field, value });
      fake.value = value;
      return { status: 'committed' };
    },
    writeMany: async () => ({}),
    follow: (_field, apply) => {
      fake.listeners.push(apply);
      return () => {};
    },
  };
  (globalThis as { PreferenceBridge?: unknown }).PreferenceBridge = fake;
  return fake;
}

afterEach(() => {
  delete (globalThis as { PreferenceBridge?: unknown }).PreferenceBridge;
});

describe('PreferenceField', () => {
  test('start reads once, follows another device, reload reads again, and start is idempotent', () => {
    const fake = install('a');
    const seen: unknown[] = [];
    const field = new PreferenceField('f', (value) => seen.push(value));
    field.start(null);
    field.start(null);
    expect(seen).toEqual(['a']);
    expect(fake.listeners).toHaveLength(1);
    fake.listeners[0]?.('b');
    field.reload();
    expect(seen).toEqual(['a', 'b', 'a']);
  });

  test('write saves ONE value under its field, and is a no-op without the bridge', async () => {
    const fake = install(null);
    const field = new PreferenceField('f', () => {});
    await field.write({ v: 1 });
    expect(fake.writes).toEqual([{ field: 'f', value: { v: 1 } }]);
    delete (globalThis as { PreferenceBridge?: unknown }).PreferenceBridge;
    await expect(field.write(1)).resolves.toBeUndefined();
  });

  test('an absent field is never written by reading it', () => {
    const fake = install(null);
    new PreferenceField('f', () => {}).start(null);
    expect(fake.writes).toEqual([]);
  });
});

describe('moves save as they happen: neither store has a draft or a cancel', () => {
  test('a move saves at once on the drawer area and a rail, and the draft methods are gone', async () => {
    const fake = install({ v: 1, items: [{ widget: 'core.ledger' }] });
    const zone = new DrawerZoneStore();
    zone.start(null);
    zone.add('core.keep-awake');
    await Promise.resolve();
    expect(fake.writes).toHaveLength(1);
    for (const store of [zone, new RailStore({ field: 'r', defaults: [], max: 8 })]) {
      for (const name of ['beginDraft', 'restoreDraft', 'stageRestore', 'endDraft']) expect(name in store).toBe(false);
    }
  });
});
