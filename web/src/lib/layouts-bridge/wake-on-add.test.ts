import { beforeEach, describe, expect, it, vi } from 'vitest';

const wake = vi.fn(async () => ({ status: 'started', detail: '' }));
const add = vi.fn(async () => ({}));
vi.mock('../../opscenter/api/asleep.svelte', () => ({ wakeOrPick: (...a: unknown[]) => wake(...(a as [])) }));
vi.mock('./api.svelte', () => ({
  addLayoutMember: (...a: unknown[]) => add(...(a as [])),
  deleteLayout: vi.fn(), layoutByUuid: vi.fn(), layouts: { data: [] }, layoutsUnavailable: { value: false },
  renameLayout: vi.fn(), reorderLayouts: vi.fn(), setLayoutStyle: vi.fn(), start: vi.fn(),
}));

describe('layoutsBridge.addMember', () => {
  beforeEach(() => {
    wake.mockClear();
    add.mockClear();
    (globalThis as Record<string, unknown>).SessionSidebar = {
      _rows: [
        { session_uuid: 'asleep-1', asleep: true, name: 'carnivore_a', label: 'A' },
        { session_uuid: 'live-1', asleep: false, name: 'carnivore_b' },
      ],
    };
  });

  it('wakes an asleep session exactly once', async () => {
    const { layoutsBridge } = await import('./bridge');
    await layoutsBridge.addMember('lay', 'asleep-1');
    expect(add).toHaveBeenCalledWith('lay', 'asleep-1');
    expect(wake).toHaveBeenCalledTimes(1);
    expect(wake).toHaveBeenCalledWith('asleep-1', 'carnivore_a', 'A');
  });

  it('does not wake a live session', async () => {
    const { layoutsBridge } = await import('./bridge');
    await layoutsBridge.addMember('lay', 'live-1');
    expect(wake).not.toHaveBeenCalled();
  });

  it('does not wake when a saved layout is read or applied (no add call)', async () => {
    const { layoutsBridge } = await import('./bridge');
    layoutsBridge.list();
    layoutsBridge.get('lay');
    expect(wake).not.toHaveBeenCalled();
  });
});
