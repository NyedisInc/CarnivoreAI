import type { Component } from 'svelte';
import { describe, expect, it } from 'vitest';
import { ensurePanel, mountInto, mountPanel } from './mount';

declare const NeedsLabel: Component<{ label: string }, Record<string, unknown>>;
declare const AllOptional: Component<{ label?: string }, Record<string, unknown>>;

export function typeOnly(target: Element): void {
  mountPanel('p', NeedsLabel, { label: 'x' });
  mountPanel('p', AllOptional);
  mountPanel('p', AllOptional, { label: 'x' });
  ensurePanel('p', NeedsLabel, { label: 'x' });
  mountInto(target, NeedsLabel, { label: 'x' });
  // @ts-expect-error a required prop cannot be skipped
  mountPanel('p', NeedsLabel);
  // @ts-expect-error a required prop cannot be skipped
  ensurePanel('p', NeedsLabel);
  // @ts-expect-error a required prop cannot be skipped
  mountInto(target, NeedsLabel);
}

describe('PropsArg', () => {
  it('is checked at compile time by npm run check', () => {
    expect(typeof typeOnly).toBe('function');
  });
});
