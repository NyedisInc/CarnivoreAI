import { afterEach, describe, expect, test, vi } from 'vitest';

import '../../lib/plugins/builtin';
import { cplugEnablement } from './enablement.svelte';
import { runCplugCardAction } from './readers';

const context = { flags: {}, refresh: vi.fn() };
const row = { name: 'cloude_api', unread: false, sessionId: 'ses_1' };

afterEach(() => {
  cplugEnablement.enabled = {};
  delete (globalThis as { API?: unknown }).API;
});

describe('runCplugCardAction', () => {
  test('runs the plugin\'s own card action while it is on (the default)', async () => {
    const setSessionUnread = vi.fn(async () => ({}));
    (globalThis as { API?: unknown }).API = { setSessionUnread };
    expect(await runCplugCardAction('unread', row, context)).toBe(true);
    expect(setSessionUnread).toHaveBeenCalledWith('cloude_api', true);
  });

  test('NEGATIVE CONTROL: answers false and runs nothing once the plugin is switched off', async () => {
    const setSessionUnread = vi.fn(async () => ({}));
    (globalThis as { API?: unknown }).API = { setSessionUnread };
    cplugEnablement.enabled = { unread: false };
    expect(await runCplugCardAction('unread', row, context)).toBe(false);
    expect(setSessionUnread).not.toHaveBeenCalled();
  });

  test('a plugin with no card action, or no plugin at all, runs nothing', async () => {
    expect(await runCplugCardAction('huddle', row, context)).toBe(false);
    expect(await runCplugCardAction('nope', row, context)).toBe(false);
  });
});
