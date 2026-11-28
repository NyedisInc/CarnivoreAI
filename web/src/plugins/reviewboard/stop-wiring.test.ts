/** @vitest-environment jsdom */
import { afterEach, describe, expect, it, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

import { cplugEnablement } from '../host/enablement.svelte';
import { startEnabled } from '../host/readers';
import TaskManagerBoardCard from '../taskmanager/TaskManagerBoardCard.svelte';
import { registerBoardAttachments, resetBoardAttachments } from '../sdk/board-attachments';
import { reviewboardCplug } from './index';

vi.mock('../../lib/resource-push/boot', () => ({
  resourcePush: () => ({ pushOrPoll: () => () => undefined, onChange: () => () => undefined, isLive: () => true }),
}));

const settle = async (): Promise<void> => { await new Promise((r) => setTimeout(r, 0)); flushSync(); };
let app: ReturnType<typeof mount> | null = null;
afterEach(() => {
  if (app) unmount(app);
  app = null;
  document.body.innerHTML = '';
  resetBoardAttachments();
});

describe('the review board plugin stop hook', () => {
  it('clears every mounted board card when the host finds the plugin switched off', async () => {
    cplugEnablement.enabled = { reviewboard: true };
    registerBoardAttachments(
      { read: async () => [{ file_id: 'a1a1a1a1', name: 'a.pdf', revision: 'r1', removed: false }], topic: 'cplug.reviewboard.boards' },
      () => cplugEnablement.enabled['reviewboard'] === true,
    );
    app = mount(TaskManagerBoardCard, { target: document.body, props: { board: { slug: 's', revision: 'r1', title: 't', summary: '' } } });
    await settle();
    expect(document.querySelectorAll('[data-task-manager-board-file]')).toHaveLength(1);
    cplugEnablement.enabled = { reviewboard: false };
    startEnabled([reviewboardCplug]);
    await settle();
    expect(document.querySelectorAll('[data-task-manager-board-file]')).toHaveLength(0);
  });
});
