/** @vitest-environment jsdom */
import { afterEach, describe, expect, test, vi } from 'vitest';
import { activateRow } from '../../lib/drawer/row-switch';
import { openFloorSession, type FloorSession } from './floor.svelte';

vi.mock('../../lib/drawer/row-switch', () => ({ activateRow: vi.fn(async () => {}) }));

function session(asleep: boolean): FloorSession {
  return { key: 'u1', name: 'cloude_x', label: 'x', sessionId: null, sessionUuid: 'u1', sessionRowId: 7, asleep,
    projectId: null, projectName: null, harness: 'claude', listing: undefined } as unknown as FloorSession;
}

function drawRow(): HTMLElement {
  const row = document.createElement('div');
  row.className = 'session-sidebar-row';
  row.dataset.name = 'cloude_x';
  document.body.append(row);
  return row;
}

afterEach(() => {
  document.body.innerHTML = '';
  delete (window as unknown as Record<string, unknown>).SessionSidebar;
  delete (window as unknown as Record<string, unknown>).SessionSidebarWakeClick;
  vi.mocked(activateRow).mockClear();
});

describe('openFloorSession', () => {
  test('a not-yet-adopted session opens through the typed activateRow with the page controller', async () => {
    const row = drawRow();
    const ctrl = { id: 'ctrl' };
    Object.assign(window, { SessionSidebar: ctrl });
    await openFloorSession(session(false));
    expect(activateRow).toHaveBeenCalledWith(ctrl, row);
  });

  test('an asleep square wakes through the row wake, handing it the typed activateRow to open with', async () => {
    const row = drawRow();
    const ctrl = { id: 'ctrl' };
    const onAsleepClick = vi.fn(async () => true);
    Object.assign(window, { SessionSidebar: ctrl, SessionSidebarWakeClick: { onAsleepClick } });
    await openFloorSession(session(true));
    expect(onAsleepClick).toHaveBeenCalledWith(ctrl, row, activateRow);
    expect(activateRow).not.toHaveBeenCalled();
  });

  test('no drawer controller, or no painted row, opens nothing', async () => {
    drawRow();
    expect(await openFloorSession(session(false))).toBe(false);
    expect(activateRow).not.toHaveBeenCalled();
  });
});
