import { afterEach, describe, expect, it, vi } from 'vitest';
import { addLocalToast, toastSurface } from './toast-surface';

const holder = globalThis as { ToastManager?: unknown };

afterEach(() => {
  delete holder.ToastManager;
});

describe('toast surface', () => {
  it('answers false and throws nothing while the classic toast script is absent', () => {
    expect(toastSurface()).toBeNull();
    expect(addLocalToast({ id: 'x' })).toBe(false);
  });

  it('hands the card to the surface when it is there', () => {
    const add = vi.fn();
    holder.ToastManager = { add };
    expect(addLocalToast({ id: 'x', local: true })).toBe(true);
    expect(add).toHaveBeenCalledWith({ id: 'x', local: true });
  });

  it('treats a surface without add() as absent', () => {
    holder.ToastManager = {};
    expect(toastSurface()).toBeNull();
  });
});
