import { describe, expect, it, vi } from 'vitest';
import { keyedLeases, sharedResources } from './shared-resource';
import type { Resource } from './poll.svelte';

function fake(): Resource<number> {
  return { stop: vi.fn() } as unknown as Resource<number>;
}

describe('sharedResources', () => {
  it('creates once per key and stops only on the last drop', () => {
    const reads = sharedResources<string, number>();
    const make = vi.fn(fake);
    const first = reads.hold('a', make);
    expect(reads.hold('a', make)).toBe(first);
    expect(make).toHaveBeenCalledTimes(1);
    reads.drop('a');
    expect(first.stop).not.toHaveBeenCalled();
    reads.drop('a');
    expect(first.stop).toHaveBeenCalledTimes(1);
    expect(reads.hold('a', make)).not.toBe(first);
  });

  it('keeps keys apart and ignores a drop with no hold', () => {
    const reads = sharedResources<number, number>();
    expect(reads.hold(1, fake)).not.toBe(reads.hold(2, fake));
    expect(() => reads.drop(9)).not.toThrow();
  });
});

describe('keyedLeases', () => {
  it('makes once, runs onLast then dispose on the last release, and rebuilds after', () => {
    const order: string[] = [];
    const leases = keyedLeases<string, { id: number }>({
      make: () => ({ id: order.length }),
      onLast: () => void order.push('last'),
      dispose: () => void order.push('dispose'),
    });
    const a = leases.hold('k');
    expect(leases.hold('k')).toBe(a);
    leases.release('k');
    expect(order).toEqual([]);
    expect(leases.release('k')).toBeUndefined();
    expect(order).toEqual(['last', 'dispose']);
    expect(leases.hold('k')).not.toBe(a);
  });

  it('waits for an async onLast and keeps the value if a newer hold arrived meanwhile', async () => {
    let finish: () => void = () => undefined;
    const dispose = vi.fn();
    const leases = keyedLeases<string, object>({
      make: () => ({}),
      onLast: () => new Promise<void>((resolve) => { finish = resolve; }),
      dispose,
    });
    const value = leases.hold('k');
    const done = leases.release('k');
    expect(leases.hold('k')).toBe(value);
    finish();
    await done;
    expect(dispose).not.toHaveBeenCalled();
    expect(leases.values()).toEqual([value]);
  });

  it('refuses a new key with no factory, ignores an unknown release, and clear disposes everything', () => {
    const dispose = vi.fn();
    const leases = keyedLeases<string, number>({ dispose });
    expect(() => leases.hold('k')).toThrow();
    leases.hold('k', () => 1);
    expect(leases.release('nope')).toBeUndefined();
    leases.clear();
    expect(dispose).toHaveBeenCalledTimes(1);
    expect(leases.values()).toEqual([]);
  });
});
