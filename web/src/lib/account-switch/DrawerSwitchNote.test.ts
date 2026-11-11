/** @vitest-environment jsdom */
import { afterEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

vi.mock('../../opscenter/api/auth.svelte', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../opscenter/api/auth.svelte')>()),
  authFetch: vi.fn(async () => ({ running_elsewhere: [] })),
}));

import DrawerSwitchNote from './DrawerSwitchNote.svelte';
import { switchActivity, switchTo } from './switch-store.svelte';

let instance: ReturnType<typeof mount> | null = null;

function noteText(id: string): string {
  instance = mount(DrawerSwitchNote, { target: document.body, props: { accountId: id } });
  flushSync();
  return document.body.textContent ?? '';
}

afterEach(() => {
  if (instance) unmount(instance);
  instance = null;
  document.body.innerHTML = '';
  Object.assign(switchActivity, { busy: null, error: null, running: [], target: null, switched: null });
});

describe('DrawerSwitchNote', () => {
  test('a click refused while another step runs says why, under the clicked account only', async () => {
    switchActivity.busy = 'other';
    expect(await switchTo('work')).toBeNull();
    expect(noteText('work')).toContain('another account step is still running');
    unmount(instance!);
    document.body.innerHTML = '';
    expect(noteText('other')).toBe('');
  });

  test('a success says new sessions moved and counts the running ones on the old login', () => {
    Object.assign(switchActivity, {
      target: 'work',
      switched: 'work',
      running: [{ session_id: 's1', tmux_session: 't1', label: 'one', provider: 'claude', account_id: 'old', active_account_id: 'work', status: 'idle' }],
    });
    const text = noteText('work');
    expect(text).toContain('new sessions now start on');
    expect(text).toContain('still on the old login: 1');
    expect(text).toContain('restart them');
  });
});
