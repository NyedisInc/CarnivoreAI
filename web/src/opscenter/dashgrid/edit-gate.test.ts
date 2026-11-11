import { describe, expect, it, vi } from 'vitest';
import { createEnableGate } from './edit-gate';

function fake(busy: boolean) {
  const handlers: Array<() => void> = [];
  const h = {
    busy,
    setEnabled: vi.fn(),
    isBusy: () => h.busy,
    on: (_e: string, fn: () => void) => {
      handlers.push(fn);
      return () => handlers.splice(handlers.indexOf(fn), 1);
    },
  };
  return { h, settle: () => handlers.slice().forEach((fn) => fn()) };
}

describe('edit toggle gate', () => {
  it('applies at once between gestures', () => {
    const { h } = fake(false);
    createEnableGate(h as never)(true);
    expect(h.setEnabled).toHaveBeenCalledWith(true);
  });

  it('a toggle during a gesture waits for the settle and applies the last wish once', () => {
    const { h, settle } = fake(true);
    const gate = createEnableGate(h as never);
    gate(false);
    gate(true);
    gate(false);
    expect(h.setEnabled).not.toHaveBeenCalled();
    h.busy = false;
    settle();
    expect(h.setEnabled).toHaveBeenCalledTimes(1);
    expect(h.setEnabled).toHaveBeenCalledWith(false);
  });
});
