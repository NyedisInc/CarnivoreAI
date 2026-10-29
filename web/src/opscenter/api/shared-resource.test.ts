import { describe, expect, it, vi } from 'vitest';
import { sharedResources } from './shared-resource';
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
