/** @vitest-environment jsdom */
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';
import { boardAnswer, round } from './fixtures';

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

let app: ReturnType<typeof mount> | null = null;

async function settle(): Promise<void> {
  for (let i = 0; i < 6; i += 1) {
    await Promise.resolve();
    await tick();
    flushSync();
  }
}

async function open(search = '?tab=reviewboard&board=20261013-bottom-bar', fold = true): Promise<void> {
  window.history.replaceState(null, '', `/static/popout.html${search}`);
  app = mount(BoardScreen, { target: document.body });
  await settle();
  if (fold) await click('[data-prompts-key]');
}

const q = <T extends Element = HTMLElement>(sel: string): T => document.querySelector(sel) as T;
const click = async (sel: string): Promise<void> => {
  q(sel).click();
  await settle();
};
async function type(sel: string, value: string): Promise<void> {
  const el = q<HTMLTextAreaElement>(sel);
  el.value = value;
  el.dispatchEvent(new Event('input', { bubbles: true }));
  await settle();
}

beforeEach(() => {
  vi.stubGlobal('ResizeObserver', class { observe(): void {} unobserve(): void {} disconnect(): void {} });
  api.fetchBoard.mockResolvedValue(boardAnswer());
  api.fetchBoards.mockResolvedValue({ boards: [] });
  api.mintTicket.mockImplementation(async (_s: string, r: string, v: string) => ({ url: `/v/${r}-${v}`, expires_in: 3600, view: v }));
  api.fetchDraft.mockResolvedValue(null);
  api.saveDraft.mockImplementation(async (_s: string, b: { rev: number }) => ({ ...b, rev: b.rev + 1 }));
  api.deleteDraft.mockResolvedValue(undefined);
  api.sendRoundKept.mockResolvedValue({ round: round(2, 'r3'), etag: 'e', delivery: { state: 'posted' }, state: 'with_claude', duplicate: false });
  api.resendRound.mockResolvedValue({ round: round(1, 'r1'), etag: 'e', delivery: { state: 'posted' }, state: 'your_turn', duplicate: false });
  api.fetchTasks.mockResolvedValue([{ id: 600, title: 'Other task', status: 'open' }]);
});

afterEach(() => {
  if (app) unmount(app);
  app = null;
  document.body.innerHTML = '';
  vi.clearAllMocks();
  vi.unstubAllGlobals();
});

describe('Joe sends a round', () => {
  it('ticks, checks, writes a note and sends under one client round id; the confirm line names the task', async () => {
    await open();
    expect(q('[data-tray]')).not.toBeNull();
    expect(q('[data-unanswered]').textContent).toContain('3');
    await click('[data-option="b"]');
    await click('[data-prompt-check="padding"]');
    await type('[data-general-note]', 'closer, keep going');
    expect(q('[data-unanswered]').textContent).toContain('1');
    await click('[data-tray-send]');
    expect(api.sendRoundKept).toHaveBeenCalledTimes(1);
    const [slug, body] = api.sendRoundKept.mock.calls[0]!;
    expect(slug).toBe('20261013-bottom-bar');
    expect(body).toMatchObject({ revision: 'r3', note: 'closer, keep going', answers: [
      { prompt: 'layout', options: ['b'] }, { prompt: 'padding', checked: true },
    ] });
    expect(body.client_round_id).toMatch(/^[0-9a-f-]{36}$/);
    expect(q('[data-confirm]')).not.toBeNull();
    expect(q('[data-confirm]').getAttribute('data-delivered')).toBe('true');
    expect(api.fetchBoard.mock.calls.length).toBeGreaterThan(1);
  });

  it('the caption counts answered, to answer and noted from the same draft the footer reads', async () => {
    await open();
    await click('[data-option="b"]');
    await type('[data-general-note]', 'closer');
    const handle = q('[data-tray-caption]').textContent ?? '';
    expect(handle).toContain('1 answered \u00b7 2 to answer \u00b7 1 noted');
    expect(handle).not.toContain(' . ');
    expect(q('[data-unanswered]').textContent).toContain('2');
  });

  it('a send and the clear icon both drop the chosen pin target and the pointed anchor readout', async () => {
    await open();
    await click('[data-anchor-pin="buttons"]');
    expect(q('[data-anchor-note="buttons"]')).not.toBeNull();
    await click('[data-option="a"]');
    await click('[data-tray-send]');
    expect(q('[data-anchor-note="buttons"]')).toBeNull();
    expect(q('[data-anchor-pin="buttons"]').getAttribute('aria-pressed')).toBe('false');
    await click('[data-anchor-pin="buttons"]');
    await click('[data-option="a"]');
    await click('[data-tray-clear]');
    expect(q('[data-anchor-note="buttons"]')).toBeNull();
  });

  it('a failed send keeps the draft, and sending again reuses the same client round id', async () => {
    api.sendRoundKept.mockRejectedValueOnce(new Error('down'));
    await open();
    await click('[data-option="a"]');
    await click('[data-tray-send]');
    expect(q('[data-send-failed]')).not.toBeNull();
    expect(q('[data-tray-send]').hasAttribute('disabled')).toBe(false);
    await click('[data-tray-send]');
    expect(api.sendRoundKept).toHaveBeenCalledTimes(2);
    expect(api.sendRoundKept.mock.calls[1]![1].client_round_id).toBe(api.sendRoundKept.mock.calls[0]![1].client_round_id);
    expect(q('[data-send-failed]')).toBeNull();
  });

  it('shows an earlier answer to the same prompt as a ghost line and copies it only on request', async () => {
    api.fetchBoard.mockResolvedValue(boardAnswer({ rounds: [round(1, 'r1', { answers: [{ prompt: 'layout', options: ['b'], note: '' }] })] }));
    await open();
    expect(q('[data-ghost="layout"]')).not.toBeNull();
    expect(q('[data-option="b"]').getAttribute('aria-checked')).toBe('false');
    await click('[data-ghost-copy="layout"]');
    expect(q('[data-option="b"]').getAttribute('aria-checked')).toBe('true');
  });

  it('opens the round a diamond shows, and offers resend for an undelivered one', async () => {
    api.fetchBoard.mockResolvedValue(boardAnswer({ rounds: [round(1, 'r1', { delivery: { state: 'undelivered', reason: 'the huddle is off' }, note: 'hello' })] }));
    await open();
    await click('[data-history="round"]');
    expect(q('[data-round-card]').getAttribute('data-delivery')).toBe('undelivered');
    expect(q('[data-round-undelivered]').textContent).toContain('huddle is off');
    await click('[data-round-resend]');
    expect(api.resendRound).toHaveBeenCalledWith('20261013-bottom-bar', 'n1');
    await click('[data-round-relink]');
    await click('[data-relink-item="600"]');
    expect(api.relinkTask).toHaveBeenCalledWith('20261013-bottom-bar', 600);
  });

  it('flip swaps the frame to the previous revision and leaves the tray as it was', async () => {
    await open();
    await click('[data-option="a"]');
    expect(q('iframe[data-board-frame]').getAttribute('src')).toBe('/v/r3-main');
    await click('[data-board-flip]');
    expect(q('iframe[data-board-frame]').getAttribute('src')).toBe('/v/r2-main');
    expect(q('[data-option="a"]').getAttribute('aria-checked')).toBe('true');
    await click('[data-board-flip]');
    expect(q('iframe[data-board-frame]').getAttribute('src')).toBe('/v/r3-main');
  });

  it('is read only on an older revision and lists the rounds sent on it', async () => {
    await open('?tab=reviewboard&board=20261013-bottom-bar&rev=r1');
    expect(q('[data-tray-send]')).toBeNull();
    expect(q('[data-tray-round="n1"]')).not.toBeNull();
  });

  it('says a newer revision landed while the draft was on an older one, and moves the notes on request', async () => {
    api.fetchDraft.mockResolvedValue({ rev: 1, revision: 'r2', answers: [], anchor_notes: [], note: 'typed on r2', client_round_id: 'c1' });
    await open();
    expect(q('[data-moved-notice]')).not.toBeNull();
    await click('[data-move-notes]');
    expect(q('[data-moved-notice]')).toBeNull();
    expect(q<HTMLTextAreaElement>('[data-general-note]').value).toBe('typed on r2');
  });
});

describe('the prompt fold-down (no sidebar)', () => {
  it('is closed by default, so the page frame has the whole width, and the header key counts what is unanswered', async () => {
    await open('?tab=reviewboard&board=20261013-bottom-bar', false);
    expect(q('[data-tray]')).toBeNull();
    expect(q('[data-prompts-key]').getAttribute('aria-expanded')).toBe('false');
    expect(q('[data-prompts-count]').textContent).toBe('3');
    expect(q('[data-board-body]')).not.toBeNull();
    expect(document.querySelector('[data-board-strip] [data-prompts-key]')).not.toBeNull();
  });

  it('folds down under the header on the key, and closes on the same key', async () => {
    await open('?tab=reviewboard&board=20261013-bottom-bar', false);
    await click('[data-prompts-key]');
    expect(q('[data-tray]')).not.toBeNull();
    expect(q('[data-prompts-key]').getAttribute('aria-expanded')).toBe('true');
    expect(q('[data-board-body] [data-tray]')).not.toBeNull();
    await click('[data-prompts-key]');
    expect(q('[data-tray]')).toBeNull();
  });

  it('the count follows the draft: one answer leaves two', async () => {
    await open();
    await click('[data-option="b"]');
    expect(q('[data-prompts-count]').textContent).toBe('2');
  });

  it('has no sidebar, no splitter, no collapse key and no column', async () => {
    await open();
    for (const gone of ['.rb-split', '[data-strip-toggle]', '[data-payload-strip]', '.rb-collapse', '[role="separator"]']) expect(document.querySelector(gone)).toBeNull();
  });

  it('opens by itself when the page points at an anchor', async () => {
    await open('?tab=reviewboard&board=20261013-bottom-bar', false);
    window.dispatchEvent(new MessageEvent('message', {
      source: q<HTMLIFrameElement>('iframe[data-board-frame]').contentWindow as MessageEventSource, origin: 'null', data: { rb: 1, type: 'ready', anchors: ['buttons'], theme_aware: true },
    }));
    window.dispatchEvent(new MessageEvent('message', {
      source: q<HTMLIFrameElement>('iframe[data-board-frame]').contentWindow as MessageEventSource, origin: 'null', data: { rb: 1, type: 'anchor', anchor: 'buttons' },
    }));
    await settle();
    expect(q('[data-tray]')).not.toBeNull();
    expect(q('[data-anchor-note="buttons"]')).not.toBeNull();
  });
});

describe('the layout contract (412 px and 900 px)', () => {
  const css = readFileSync(resolve(process.cwd(), 'src/cplugs/reviewboard/tray.css'), 'utf8');

  it('the fold-down is capped so the page keeps room', () => {
    expect(css).toMatch(/\.rb-fold\s*\{[^}]*max-height:\s*55%/);
  });

  it('a round card is a bottom sheet by default and a right-hand card when the board has 900 px of room', () => {
    expect(css).toMatch(/\.rb-over\s*\{[^}]*bottom:\s*0/);
    expect(css).toMatch(/@container rb \(min-width: 900px\)\s*\{\s*\.rb-over\s*\{[^}]*width:\s*360px/);
  });

  it('has no column, splitter or bottom-sheet handle left in the stylesheet', () => {
    for (const gone of ['rb-split', 'rb-tray', 'rb-handle', 'rb-grip', 'rb-collapse', 'rb-strip-head', '--rb-strip-w']) expect(css.replace(/\/\*[\s\S]*?\*\//g, '')).not.toContain(gone);
  });

  it('lets the main column and the stage shrink, so a mockup as wide as the window cannot push the page off screen', () => {
    expect(css).toMatch(/\.rb-main\s*\{[^}]*min-width:\s*0/);
    const board = readFileSync(resolve(process.cwd(), 'src/cplugs/reviewboard/board.css'), 'utf8');
    expect(board).toMatch(/\.rb-stage\s*\{[^}]*min-width:\s*0/);
    expect(css).toMatch(/\.rb-body\s*\{[^}]*min-width:\s*0/);
  });

  it('scrolls a focused control in above the footer, not under it', () => {
    expect(css).toMatch(/\.rb-fold-body\s*\{[^}]*scroll-padding-block:\s*12px/);
  });

  it('uses tokens only: no hex, rgb or named color', () => {
    for (const file of ['tray.css', 'header.css', 'board.css']) {
      const text = readFileSync(resolve(process.cwd(), `src/cplugs/reviewboard/${file}`), 'utf8');
      expect(text.replace(/\/\*[\s\S]*?\*\//g, '')).not.toMatch(/#[0-9a-fA-F]{3,8}\b|rgba?\(/);
    }
  });
});
