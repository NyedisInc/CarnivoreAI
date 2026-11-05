/** @vitest-environment jsdom */
import { afterEach, expect, test, vi } from 'vitest';
import { SessionSidebarController } from './controller';

afterEach(() => {
  vi.restoreAllMocks();
  document.body.className = '';
  document.body.replaceChildren();
});

function controller(): { ctrl: SessionSidebarController; panel: HTMLElement } {
  vi.spyOn(SessionSidebarController, 'SUPPORTS_INERT', 'get').mockReturnValue(true);
  const panel = document.createElement('aside');
  const listEl = document.createElement('div');
  panel.append(listEl);
  document.body.append(panel);
  const ctrl = new SessionSidebarController();
  ctrl.panel = panel;
  ctrl.listEl = listEl;
  ctrl._fetchAndRender = async () => {};
  ctrl._startPoll = () => {};
  return { ctrl, panel };
}

test('open raises ps-drawer-open and close clears it, in step with the panel class', () => {
  const { ctrl, panel } = controller();
  ctrl.open({ persist: false });
  expect(panel.classList.contains('session-sidebar-panel--open')).toBe(true);
  expect(document.body.classList.contains('ps-drawer-open')).toBe(true);
  ctrl.close({ persist: false });
  expect(panel.classList.contains('session-sidebar-panel--open')).toBe(false);
  expect(document.body.classList.contains('ps-drawer-open')).toBe(false);
});
