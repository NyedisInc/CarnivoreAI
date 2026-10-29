import { afterEach, describe, expect, it, vi } from 'vitest';
import { preferenceField, SAVE_NO_ANSWER, SAVE_UNAVAILABLE } from './field';

function install(bridge: Record<string, unknown> | undefined): void {
  (globalThis as { PreferenceBridge?: unknown }).PreferenceBridge = bridge;
}

const coerce = (value: unknown): number => (typeof value === 'number' ? value : 0);

afterEach(() => install(undefined));

describe('preferenceField', () => {
  it('reads the fallback through the coercer with no bridge, and says unavailable on save', async () => {
    const field = preferenceField('x', coerce, 7);
    expect(field.read()).toBe(0);
    expect(await field.save(1)).toBe(SAVE_UNAVAILABLE);
    expect(field.follow(() => {})()).toBeUndefined();
  });

  it('coerces what the bridge holds and passes the fallback as the local reader', () => {
    const read = vi.fn((_name: string, local: () => unknown) => local());
    install({ read });
    expect(preferenceField('x', coerce, 7).read()).toBe(7);
    install({ read: () => 5 });
    expect(preferenceField('x', coerce, 7).read()).toBe(5);
  });

  it('saves null for committed and unchanged, else the reason', async () => {
    for (const status of ['committed', 'unchanged']) {
      install({ read: () => null, write: async () => ({ status }) });
      expect(await preferenceField('x', coerce, 0).save(1)).toBeNull();
    }
    install({ read: () => null, write: async () => ({ status: 'conflict', detail: 'stale' }) });
    expect(await preferenceField('x', coerce, 0).save(1)).toBe('stale');
    install({ read: () => null, write: async () => null });
    expect(await preferenceField('x', coerce, 0).save(1)).toBe(SAVE_NO_ANSWER);
  });

  it('follows through the coercer', () => {
    const apply = vi.fn();
    install({ read: () => null, follow: (_n: string, cb: (v: unknown) => void) => { cb('bad'); cb(3); return () => {}; } });
    preferenceField('x', coerce, 0).follow(apply);
    expect(apply.mock.calls).toEqual([[0], [3]]);
  });
});
