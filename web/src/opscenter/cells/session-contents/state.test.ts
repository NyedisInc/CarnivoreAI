import { describe, expect, test, vi } from 'vitest';

vi.mock('./api', () => ({ getContents: () => new Promise(() => undefined) }));

import { acquireContents } from './state.svelte';

describe('contents leases', () => {
  test('a double release keeps the other holder\'s hold', () => {
    const first = acquireContents(7);
    const second = acquireContents(7);
    first.release();
    first.release();
    const third = acquireContents(7);
    expect(third.store).toBe(second.store);
    second.release();
    third.release();
    expect(acquireContents(7).store).not.toBe(second.store);
  });
});
