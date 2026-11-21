/** @vitest-environment jsdom */
import { afterEach, describe, expect, it, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

import { registerRoundOpener, resetRoundOpener } from '../sdk/round-opener';
import TaskManagerRoundCard from './TaskManagerRoundCard.svelte';

const opener = vi.fn(async () => undefined);

let app: ReturnType<typeof mount> | null = null;
afterEach(() => {
  if (app) unmount(app);
  app = null;
  document.body.innerHTML = '';
  resetRoundOpener();
  vi.clearAllMocks();
});

describe('the round card', () => {
  const text = 'review round 2 on r2 (bottom bar), 412px\nwhich row: two rows\nnote: closer\nread it: task_manager_board_get {"board": "b", "since_round": 1}';

  it('draws the round lines and leaves the agent line out', () => {
    app = mount(TaskManagerRoundCard, { target: document.body, props: { round: { slug: '20261013-bottom-bar', round: 'n2', revision: 'r2' }, text } });
    flushSync();
    const card = document.querySelector('[data-task-manager-round="n2"]')!;
    expect(card.textContent).toContain('review round 2 on r2 (bottom bar), 412px');
    expect(card.textContent).toContain('which row: two rows');
    expect(card.textContent).not.toContain('task_manager_board_get');
  });

  it('opens the board at the round revision through the opener a plugin registered', () => {
    registerRoundOpener(opener);
    app = mount(TaskManagerRoundCard, { target: document.body, props: { round: { slug: '20261013-bottom-bar', round: 'n2', revision: 'r2' }, text } });
    flushSync();
    (document.querySelector('[data-task-manager-round-open]') as HTMLButtonElement).click();
    expect(opener).toHaveBeenCalledWith({ slug: '20261013-bottom-bar', revision: 'r2' });
  });

  it('shows the lines and no open button while no plugin registered an opener', () => {
    app = mount(TaskManagerRoundCard, { target: document.body, props: { round: { slug: '20261013-bottom-bar', round: 'n2', revision: 'r2' }, text } });
    flushSync();
    expect(document.querySelector('[data-task-manager-round="n2"]')!.textContent).toContain('which row: two rows');
    expect(document.querySelector('[data-task-manager-round-open]')).toBeNull();
  });
});
