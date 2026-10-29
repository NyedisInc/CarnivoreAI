/** @vitest-environment jsdom */
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { afterEach, describe, expect, test, vi } from 'vitest';
import { openFloorSession, type FloorSession } from '../../sdk/floor.svelte';

const here = path.dirname(fileURLToPath(import.meta.url));

function asleepSession(): FloorSession {
  return { key: 'u1', name: 'cloude_asleep', label: 'asleep one', sessionId: null, sessionUuid: 'u1', sessionRowId: 7, asleep: true,
    projectId: null, projectName: null, harness: 'claude', listing: undefined } as unknown as FloorSession;
}

afterEach(() => {
  document.body.innerHTML = '';
  delete (window as unknown as Record<string, unknown>).SessionSidebar;
  delete (window as unknown as Record<string, unknown>).SessionSidebarClicks;
  delete (window as unknown as Record<string, unknown>).SessionSidebarWakeClick;
});

describe('PANELFIX', () => {
  test('A: an asleep square wakes through the row wake, then opens through activateRow', async () => {
    const row = document.createElement('div');
    row.className = 'session-sidebar-row';
    row.dataset.name = 'cloude_asleep';
    row.dataset.asleep = '1';
    document.body.append(row);
    const ctrl = {};
    const activateRow = vi.fn(async () => {});
    const onAsleepClick = vi.fn(async () => true);
    Object.assign(window, { SessionSidebar: ctrl, SessionSidebarClicks: { activateRow }, SessionSidebarWakeClick: { onAsleepClick } });
    await openFloorSession(asleepSession());
    expect(onAsleepClick).toHaveBeenCalledTimes(1);
    expect(onAsleepClick).toHaveBeenCalledWith(ctrl, row, activateRow);
    expect(activateRow).not.toHaveBeenCalled();
  });

  test('B: the panel scroller hides its x axis', () => {
    const src = fs.readFileSync(path.join(here, '..', 'HuddleBody.svelte'), 'utf8');
    const rule = /\.hd-swarm\s*\{([^}]*)\}/.exec(src)?.[1] ?? '';
    expect(rule).toMatch(/overflow-x:\s*hidden/);
  });
});
