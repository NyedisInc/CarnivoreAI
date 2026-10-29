/** @vitest-environment jsdom */
import { afterEach, describe, expect, test, vi } from 'vitest';
import { mount, unmount } from 'svelte';

vi.mock('../../../opscenter/api/auth.svelte', async (importOriginal) => {
  const real = await importOriginal<typeof import('../../../opscenter/api/auth.svelte')>();
  return {
    ...real,
    authFetch: async (path: string) => {
      if (path === '/swarm/agents/7') return { id: 7, display_name: 'Loki', rank: 'project', state: 'torn_down', thread_key: '12', session_id: null, tmux_session: null };
      if (path.startsWith('/swarm/agents/7/conversation')) return { entries: [], cursor: null };
      return {};
    },
  };
});

import ChatWidget from './ChatWidget.svelte';
import { chatSlotId } from './chat-model';

let app: object | null = null;

afterEach(() => {
  if (app) void unmount(app);
  app = null;
});

describe('a turned-off agent chat', () => {
  test('the header says turned off, and a titled page flags the strip', async () => {
    document.body.innerHTML = '<div id="host"></div>';
    app = mount(ChatWidget, { target: document.getElementById('host') as HTMLElement, props: { instance: chatSlotId(7), titled: true } });
    await vi.waitFor(() => expect(document.querySelector('[data-agent-state="torn_down"]')).not.toBeNull());
    expect(document.querySelector('[data-agent-state="torn_down"]')?.textContent?.trim()).toBe('turned off');
    expect(document.querySelector('.hdc-bar--titled')).not.toBeNull();
  });
});
