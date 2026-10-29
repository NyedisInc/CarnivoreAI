/** @vitest-environment jsdom */
import { afterEach, describe, expect, test, vi } from 'vitest';
import { mount, unmount } from 'svelte';

const rows: Record<string, Record<string, unknown>> = {
  working: { activity_status: 'working', unread: false, tmux_session: 't1' },
  unread: { activity_status: 'idle', unread: true, startup_gate: null, status_source: 'registry', tmux_session: 't2' },
};

vi.mock('../../sdk', async (importOriginal) => {
  const real = await importOriginal<typeof import('../../sdk')>();
  return { ...real, sessionRow: (id: string | null) => (id ? rows[id] : undefined) };
});

import ChatBar from './ChatBar.svelte';

let app: object | null = null;
afterEach(() => {
  if (app) void unmount(app);
  app = null;
});

function led(sessionId: string | null): HTMLElement {
  document.body.innerHTML = '<div id="host"></div>';
  const agent = { id: 1, display_name: 'Loki', rank: 'project', state: 'running', session_id: sessionId } as never;
  app = mount(ChatBar, { target: document.getElementById('host') as HTMLElement, props: { agentId: 1, agent, chat: null } });
  return document.querySelector('.status-led') as HTMLElement;
}

describe('chat bar light', () => {
  test('reflects the row status', () => {
    const el = led('working');
    expect(el).not.toBeNull();
    expect(document.querySelector('[data-chat-bar-led="working"]')).not.toBeNull();
    expect(el.dataset.inner).toBe('working');
  });

  test('reflects unread differently from the same status read', () => {
    const read = led('working').dataset.outer;
    const unread = led('unread');
    expect(unread.dataset.outer).not.toBe(read);
  });

  test('an agent with no live row shows the idle light', () => {
    led(null);
    expect(document.querySelector('[data-chat-bar-led="idle"]')).not.toBeNull();
  });
});
