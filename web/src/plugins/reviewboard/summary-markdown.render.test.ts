/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';
import { boardAnswer, revision, round } from './fixtures';

const api = vi.hoisted(() => ({
  fetchBoard: vi.fn(), fetchBoards: vi.fn(), rescan: vi.fn(), mintTicket: vi.fn(), clearScratch: vi.fn(),
  fetchDraft: vi.fn(), saveDraft: vi.fn(), deleteDraft: vi.fn(), sendRoundKept: vi.fn(), resendRound: vi.fn(), relinkTask: vi.fn(), fetchTasks: vi.fn(),
  fetchAttachments: vi.fn(async (slug: string) => ({ slug, attachments: [] })), fetchAttachmentBlob: vi.fn(),
}));
vi.mock('./board-api', () => api);
vi.mock('../../lib/resource-push/boot', () => ({
  resourcePush: () => ({ pushOrPoll: () => () => {}, onChange: () => () => {}, isLive: () => true }),
}));

import BoardScreen from './BoardScreen.svelte';
import { registerMarkdown } from '../sdk';
import TaskManagerMarkdown from '../huddle/TaskManagerMarkdown.svelte';
import { mdPlain } from '../huddle/task-manager-markdown';

let app: ReturnType<typeof mount> | null = null;
const SUMMARY = '**Stats:** two rows now\n- bigger buttons\n- <img src=x onerror=alert(1)>';

async function settle(): Promise<void> {
  for (let i = 0; i < 6; i += 1) {
    await Promise.resolve();
    await tick();
    flushSync();
  }
}

beforeEach(() => {
  registerMarkdown({ Block: TaskManagerMarkdown, plain: mdPlain });
  vi.stubGlobal('ResizeObserver', class { observe(): void {} unobserve(): void {} disconnect(): void {} });
  api.fetchBoard.mockResolvedValue(boardAnswer({ revisions: [revision(1), revision(2), revision(3, { summary: SUMMARY, answers_round: 'n1' })] }));
  api.fetchBoards.mockResolvedValue({ boards: [] });
  api.mintTicket.mockImplementation(async (_s: string, r: string, v: string) => ({ url: `/v/${r}-${v}`, expires_in: 3600, view: v }));
  api.fetchDraft.mockResolvedValue(null);
  api.fetchTasks.mockResolvedValue([]);
  window.history.replaceState(null, '', '/static/popout.html?tab=reviewboard&board=20261013-bottom-bar');
});

afterEach(() => {
  if (app) unmount(app);
  app = null;
  document.body.innerHTML = '';
  vi.clearAllMocks();
  vi.unstubAllGlobals();
});

describe('a revision summary reads as markdown', () => {
  it('draws strong and list items in the what-changed block, with no raw markers and no injected element', async () => {
    app = mount(BoardScreen, { target: document.body });
    await settle();
    (document.querySelector('[data-prompts-key]') as HTMLElement).click();
    await settle();
    const block = document.querySelector('[data-changed-summary]') as HTMLElement;
    expect(block.querySelector('strong')?.textContent).toBe('Stats:');
    expect(block.querySelectorAll('li').length).toBe(2);
    expect(block.textContent).not.toContain('**');
    expect(block.querySelector('img')).toBeNull();
  });

  it('shows the bar under the page as plain words on one run, markers stripped', async () => {
    app = mount(BoardScreen, { target: document.body });
    await settle();
    const bar = document.querySelector('[data-board-summary]') as HTMLElement;
    expect(bar.textContent).toContain('Stats: two rows now');
    expect(bar.textContent).not.toMatch(/\*\*|^- /m);
    expect(bar.querySelector('strong, li')).toBeNull();
  });
});
