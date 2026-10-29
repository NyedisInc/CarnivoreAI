import { afterEach, describe, expect, it, vi } from 'vitest';
import { cellTearOffTarget, pastWindowEdge, releaseTearOff, tabTearOffTarget, tearOffCell } from './tearoff';

function fakeWindow(tearOff?: (...args: unknown[]) => Promise<boolean>): Window {
  return { innerWidth: 1000, innerHeight: 700, carnivoreDesktop: tearOff ? { tearOff } : {} } as unknown as Window;
}
const at = (clientX: number, clientY: number) => ({ clientX, clientY, screenX: clientX + 300, screenY: clientY + 120 });

afterEach(() => vi.unstubAllGlobals());

describe('what is torn out', () => {
  it('keeps a terminal tab on its row key', () => {
    expect(tabTearOffTarget('terminal:row:7')).toEqual({ kind: 'terminal', id: '7' });
    expect(tabTearOffTarget('terminal:ses_b')).toBeNull();
    expect(tabTearOffTarget('terminal:row:7;x')).toBeNull();
  });
  it('takes a widget tab and a widget cell as the widget', () => {
    expect(tabTearOffTarget('widget:core.tasks')).toEqual({ kind: 'widget', id: 'core.tasks' });
    expect(cellTearOffTarget('core.tasks')).toEqual({ kind: 'widget', id: 'core.tasks' });
    expect(cellTearOffTarget('terminal:row:7')).toBeNull();
  });
});

describe('the edge', () => {
  it('is any side of the viewport', () => {
    const win = fakeWindow();
    for (const [x, y] of [[-1, 10], [10, -1], [1000, 10], [10, 700]] as const) expect(pastWindowEdge(win, at(x, y))).toBe(true);
    expect(pastWindowEdge(win, at(0, 0))).toBe(false);
    expect(pastWindowEdge(win, at(999, 699))).toBe(false);
  });
});

describe('releaseTearOff', () => {
  it('calls the bridge once with the kind, the id and the cursor on a release past the edge', async () => {
    const tearOff = vi.fn().mockResolvedValue(true);
    const pending = releaseTearOff(fakeWindow(tearOff), tabTearOffTarget('terminal:row:7'), at(1040, 200));
    expect(await pending).toBe(true);
    expect(tearOff).toHaveBeenCalledTimes(1);
    expect(tearOff).toHaveBeenCalledWith('terminal', '7', 1340, 320);
  });
  it('never fires on an in-window drag', () => {
    const tearOff = vi.fn().mockResolvedValue(true);
    expect(releaseTearOff(fakeWindow(tearOff), { kind: 'terminal', id: '7' }, at(500, 300))).toBeNull();
    expect(tearOff).not.toHaveBeenCalled();
  });
  it('does nothing without the bridge, or without a target (a plain browser)', () => {
    expect(releaseTearOff(fakeWindow(), { kind: 'terminal', id: '7' }, at(1040, 200))).toBeNull();
    expect(releaseTearOff({ innerWidth: 1000, innerHeight: 700 } as unknown as Window, { kind: 'terminal', id: '7' }, at(-5, 5))).toBeNull();
    const tearOff = vi.fn().mockResolvedValue(true);
    expect(releaseTearOff(fakeWindow(tearOff), null, at(1040, 200))).toBeNull();
    expect(tearOff).not.toHaveBeenCalled();
  });
  it('answers false, not a throw, when the app refuses', async () => {
    vi.spyOn(console, 'warn').mockImplementation(() => undefined);
    const pending = releaseTearOff(fakeWindow(vi.fn().mockRejectedValue(new Error('no'))), { kind: 'widget', id: 'core.tasks' }, at(-3, 9));
    expect(await pending).toBe(false);
  });
  it('tears a widget cell out through the page window and tells the caller to skip its drop', () => {
    const tearOff = vi.fn().mockResolvedValue(true);
    vi.stubGlobal('window', fakeWindow(tearOff));
    expect(tearOffCell('core.tasks', at(1100, 50))).toBe(true);
    expect(tearOff).toHaveBeenCalledWith('widget', 'core.tasks', 1400, 170);
    expect(tearOffCell('core.tasks', at(10, 50))).toBe(false);
    expect(tearOff).toHaveBeenCalledTimes(1);
  });
});
