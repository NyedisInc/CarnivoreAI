/** @vitest-environment jsdom */
import { afterEach, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';
import type { LayoutMember } from './api';

const toggle = vi.fn(async (_member: LayoutMember) => null);
vi.mock('./broadcast.svelte', () => ({
  broadcastOn: (member: LayoutMember) => member.session_row_id <= 3,
  memberName: (member: LayoutMember) => `agent-${member.session_row_id}`,
  recipients: () => ({ receiving: 3, total: 5, busy: [] }),
  toggleBroadcast: (member: LayoutMember) => toggle(member),
}));

import LayoutCommandBar from './LayoutCommandBar.svelte';
import { layoutMode } from './mode.svelte';

(HTMLElement.prototype as { showPopover?: () => void }).showPopover ??= () => {};
(HTMLElement.prototype as { hidePopover?: () => void }).hidePopover ??= () => {};
vi.stubGlobal('ResizeObserver', class { observe(): void {} disconnect(): void {} unobserve(): void {} });

const mounted: ReturnType<typeof mount>[] = [];
afterEach(async () => {
  for (const component of mounted.splice(0)) await unmount(component);
  document.body.replaceChildren();
  layoutMode.uuid = '';
  layoutMode.members = [];
});

function open(): HTMLElement {
  layoutMode.uuid = 'L1';
  layoutMode.name = 'work';
  layoutMode.members = [1, 2, 3, 4, 5].map((n) => ({ session_row_id: n, position: n }) as unknown as LayoutMember);
  const host = document.createElement('div');
  document.body.append(host);
  mounted.push(mount(LayoutCommandBar, { target: host }));
  flushSync();
  return host;
}

test('command mode shows "to 3 of 5" and a menu row flips its member', () => {
  const host = open();
  expect(host.querySelector('[data-bar-tool="recipients"]')).toBeNull();
  (host.querySelector('[data-bar-toggle="command"]') as HTMLButtonElement).click();
  flushSync();
  const chip = host.querySelector('[data-bar-tool="recipients"]') as HTMLButtonElement;
  expect(chip.textContent?.trim()).toBe('to 3 of 5');
  expect(document.querySelector('[role="menu"]'), 'closed until the chip is pressed').toBeNull();
  chip.click();
  flushSync();
  const rows = document.querySelectorAll<HTMLButtonElement>('[role="menuitemcheckbox"]');
  expect(rows).toHaveLength(5);
  rows[3]!.click();
  expect(toggle).toHaveBeenCalledTimes(1);
  expect((toggle.mock.calls[0]![0] as LayoutMember).session_row_id).toBe(4);
});
