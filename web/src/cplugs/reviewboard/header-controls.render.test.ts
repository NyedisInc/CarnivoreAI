/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';
import { boardAnswer, revision, round } from './fixtures';
import type { BoardSave, PayloadDraft } from './board-model';
import { AUTOSAVE_MS, ECHO_MS } from './payload-loop.svelte';
import { registerThemeSource } from './board-theme';

const api = vi.hoisted(() => ({
  fetchBoard: vi.fn(), fetchBoards: vi.fn(), rescan: vi.fn(), mintTicket: vi.fn(), clearScratch: vi.fn(),
  fetchDraft: vi.fn(), saveDraft: vi.fn(), deleteDraft: vi.fn(), sendRoundKept: vi.fn(), resendRound: vi.fn(), relinkTask: vi.fn(), fetchTasks: vi.fn(),
  savePayloadDraft: vi.fn(),
  fetchAttachments: vi.fn(async (slug: string) => ({ slug, attachments: [] })), fetchAttachmentBlob: vi.fn(),
}));
vi.mock('./board-api', () => api);
vi.mock('../../lib/resource-push/boot', () => ({
  resourcePush: () => ({ pushOrPoll: () => () => {}, onChange: () => () => {}, isLive: () => true }),
}));
const themeApi = vi.hoisted(() => ({
  themeChoices: vi.fn(), activeThemeId: vi.fn(), themeTokens: vi.fn(),
}));
vi.mock('../sdk', async (importOriginal) => ({ ...(await importOriginal<typeof import('../sdk')>()), ...themeApi }));

import BoardScreen from './BoardScreen.svelte';

let app: ReturnType<typeof mount> | null = null;

const save = (n: number, payload: Record<string, unknown>, note?: string): BoardSave => ({ n, at: `2026-10-13T15:0${n}:00Z`, payload, ...(note ? { note } : {}) });
const SAVES = [save(1, { milk: false }), save(2, { milk: true }, 'milk yes'), save(3, { milk: true, eggs: 2 })];
const THEMES = [{ id: 'carnivore', name: 'Carnivore' }, { id: 'dracula', name: 'Dracula' }, { id: 'matrix', name: 'Matrix' }];
const TOKENS: Record<string, Record<string, string>> = {
  carnivore: { '--oc-ground-page': 'rgb(2, 22, 30)', '--oc-orange': 'rgb(255, 70, 82)' },
  dracula: { '--oc-ground-page': 'rgb(30, 31, 41)', '--oc-orange': 'rgb(189, 147, 249)' },
};

function payloadBoard(draft?: PayloadDraft) {
  return boardAnswer({ revisions: [revision(1), revision(2), revision(3, { prompts: [], anchors: [], payload_mode: true, saves: SAVES, ...(draft ? { draft } : {}) })] });
}

async function settle(): Promise<void> {
  for (let i = 0; i < 6; i += 1) {
    await Promise.resolve();
    await tick();
    flushSync();
  }
}

async function open(search = '?tab=reviewboard&board=20261013-bottom-bar'): Promise<void> {
  window.history.replaceState(null, '', `/static/popout.html${search}`);
  app = mount(BoardScreen, { target: document.body });
  await settle();
}

const q = <T extends Element = HTMLElement>(sel: string): T => document.querySelector(sel) as T;
const frame = (): HTMLIFrameElement => q<HTMLIFrameElement>('iframe[data-board-frame]');
async function fromFrame(data: unknown): Promise<void> {
  window.dispatchEvent(new MessageEvent('message', { source: frame().contentWindow as MessageEventSource, origin: 'null', data }));
  await settle();
}
const readyAt = (): Promise<void> => fromFrame({ rb: 1, type: 'ready', anchors: [], theme_aware: true });
async function quiet(): Promise<void> {
  await vi.advanceTimersByTimeAsync(ECHO_MS + 10);
  await settle();
}
async function ready(): Promise<void> {
  await readyAt();
  await quiet();
}
const post = (payload: unknown): Promise<void> => fromFrame({ rb: 1, type: 'payload', payload });
async function click(sel: string): Promise<void> {
  q(sel).click();
  await settle();
}
async function passDebounce(): Promise<void> {
  await vi.advanceTimersByTimeAsync(AUTOSAVE_MS + 10);
  await settle();
}

beforeEach(() => {
  vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout', 'Date'] });
  vi.stubGlobal('ResizeObserver', class { observe(): void {} unobserve(): void {} disconnect(): void {} });
  api.fetchBoard.mockResolvedValue(payloadBoard());
  api.fetchBoards.mockResolvedValue({ boards: [] });
  api.mintTicket.mockImplementation(async (_s: string, r: string, v: string) => ({ url: `/v/${r}-${v}`, expires_in: 3600, view: v }));
  api.fetchDraft.mockResolvedValue(null);
  api.savePayloadDraft.mockResolvedValue({ revision: 'r3', draft: { at: '2026-10-14T09:00:00Z' }, etag: 'e2', changed: true });
  api.sendRoundKept.mockResolvedValue({ round: { ...round(2, 'r3'), save: 4, payload: {} }, etag: 'e', delivery: { state: 'posted' }, state: 'with_claude', duplicate: false });
  themeApi.themeChoices.mockReturnValue(THEMES);
  themeApi.activeThemeId.mockReturnValue('carnivore');
  themeApi.themeTokens.mockImplementation((id: string) => TOKENS[id] ?? { '--oc-orange': 'rgb(1, 2, 3)' });
  vi.stubGlobal('crypto', { randomUUID: () => '11111111-1111-4111-8111-111111111111' });
  localStorage.clear();
});

afterEach(() => {
  if (app) unmount(app);
  app = null;
  document.body.innerHTML = '';
  vi.clearAllMocks();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe('the header carries the controls and there is no sidebar', () => {
  it('puts the save disk, the save stepper, the note key, the theme picker and Send in the title bar', async () => {
    await open();
    await ready();
    await post({ milk: true, eggs: 3 });
    const header = q('[data-board-strip]');
    for (const sel of ['[data-payload-controls]', '[data-payload-saves]', '[data-payload-note-key]', '[data-theme-picker]', '[data-payload-send]', '[data-payload-light]']) {
      expect(header.querySelector(sel), sel).not.toBeNull();
    }
    expect(q('[data-payload-send]').getAttribute('data-btn')).toBe('confirm');
    expect(q('[data-payload-send]').getAttribute('data-size')).toBe('sm');
    expect(q('[data-payload-controls] [data-notes-save]')).toBe(q('[data-payload-light]'));
    for (const gone of ['[data-fit-key]', '.rb-state[data-state="your_turn"]']) expect(header.querySelector(gone), gone).toBeNull();
    const labels = [...header.querySelectorAll('button')].map((b) => b.getAttribute('aria-label') ?? '');
    expect(labels.some((l) => /fit to the width|real width/.test(l))).toBe(false);
    expect(header.textContent).not.toContain('your turn');
  });

  it('has no strip, tray, splitter, collapse key or Save key, and the page frame sits in a single full-width column', async () => {
    await open();
    for (const gone of ['[data-payload-strip]', '[data-tray]', '.rb-split', '[data-strip-toggle]', '.rb-collapse', '[data-payload-save]', '[role="separator"]', 'aside']) {
      expect(document.querySelector(gone), gone).toBeNull();
    }
    expect(q('[data-board-body]').getAttribute('style') ?? '').not.toContain('--rb-strip-w');
    expect(q('[data-board-body] [data-board-stage] iframe')).not.toBeNull();
  });

  it('shows no prompts key on a payload page and no payload controls on a prompt board', async () => {
    await open();
    expect(q('[data-prompts-key]')).toBeNull();
    if (app) unmount(app);
    document.body.innerHTML = '';
    await open('?tab=reviewboard&board=20261013-bottom-bar&rev=r2');
    expect(q('[data-payload-controls]')).toBeNull();
    expect(q('[data-prompts-key]')).not.toBeNull();
    expect(q('[data-theme-picker]')).not.toBeNull();
  });
});

describe('autosave: one overwriting draft, never a numbered save', () => {
  it('waits out the debounce, writes the page state once as the draft, and the light goes saving then saved', async () => {
    await open();
    await ready();
    await post({ milk: true, eggs: 3 });
    expect(q('[data-payload-light]').getAttribute('data-draft-state')).toBe('pending');
    expect(q('[data-payload-light]').getAttribute('aria-label')).toBe('not saved yet, click to save now');
    expect(q('[data-payload-light]').dataset.notesLight).toBe('pending');
    await vi.advanceTimersByTimeAsync(AUTOSAVE_MS - 100);
    expect(api.savePayloadDraft).not.toHaveBeenCalled();
    await passDebounce();
    expect(api.savePayloadDraft).toHaveBeenCalledTimes(1);
    expect(api.savePayloadDraft).toHaveBeenCalledWith('20261013-bottom-bar', { revision: 'r3', payload: { milk: true, eggs: 3 } }, false);
    expect(q('[data-payload-light]').getAttribute('data-draft-state')).toBe('saved');
    expect(q('[data-payload-light]').getAttribute('aria-label')).toBe('saved');
    expect(q('[data-payload-light]').dataset.notesLight).toBe('saved');
    expect(api.sendRoundKept).not.toHaveBeenCalled();
  });

  it('coalesces a burst of edits into the last state', async () => {
    await open();
    await ready();
    await post({ n: 1 });
    await vi.advanceTimersByTimeAsync(800);
    await post({ n: 2 });
    await vi.advanceTimersByTimeAsync(800);
    await post({ n: 3 });
    await passDebounce();
    expect(api.savePayloadDraft).toHaveBeenCalledTimes(1);
    expect(api.savePayloadDraft.mock.calls[0]![1].payload).toEqual({ n: 3 });
  });

  it('says "not saved" with the reason when the server refuses, and the next edit tries again', async () => {
    api.savePayloadDraft.mockRejectedValueOnce(new Error('that payload is over 64 KiB'));
    await open();
    await ready();
    await post({ a: 1 });
    await passDebounce();
    expect(q('[data-payload-light]').getAttribute('data-draft-state')).toBe('failed');
    expect(q('[data-payload-light]').getAttribute('aria-label')).toBe('not saved: that payload is over 64 KiB');
    expect(q('[data-payload-light]').dataset.notesLight).toBe('error');
    await post({ a: 2 });
    await passDebounce();
    expect(api.savePayloadDraft).toHaveBeenCalledTimes(2);
    expect(q('[data-payload-light]').getAttribute('aria-label')).toBe('saved');
  });

  it('says so when the bridge refused the page state (too big or not plain data)', async () => {
    await open();
    await ready();
    await post([1, 2, 3]);
    expect(q('[data-payload-light]').getAttribute('data-draft-state')).toBe('failed');
    expect(q('[data-payload-light]').getAttribute('aria-label')).toContain('too big or not plain data');
    expect(api.savePayloadDraft).not.toHaveBeenCalled();
  });

  it('ignores a state the page posts before it was told where to start, and the echo of a state the board handed it', async () => {
    await open();
    await post({ early: true });
    await passDebounce();
    expect(api.savePayloadDraft).not.toHaveBeenCalled();
    await readyAt();
    await post(SAVES[2]!.payload);
    await post({ defaults: true });
    await passDebounce();
    expect(api.savePayloadDraft).not.toHaveBeenCalled();
    expect(q<HTMLButtonElement>('[data-payload-light]').disabled).toBe(true);
  });

  it('flushes at once when the tab is hidden and when the page is going away, with keepalive', async () => {
    await open();
    await ready();
    await post({ a: 1 });
    Object.defineProperty(document, 'visibilityState', { value: 'hidden', configurable: true });
    document.dispatchEvent(new Event('visibilitychange'));
    await settle();
    Object.defineProperty(document, 'visibilityState', { value: 'visible', configurable: true });
    expect(api.savePayloadDraft).toHaveBeenCalledTimes(1);
    expect(api.savePayloadDraft).toHaveBeenCalledWith('20261013-bottom-bar', { revision: 'r3', payload: { a: 1 } }, true);
    await post({ a: 2 });
    window.dispatchEvent(new Event('pagehide'));
    await settle();
    expect(api.savePayloadDraft).toHaveBeenCalledTimes(2);
    expect(api.savePayloadDraft.mock.calls[1]![2]).toBe(true);
  });

  it('writes nothing when the page returns to the state the server already holds', async () => {
    await open();
    await ready();
    await post({ a: 1 });
    await passDebounce();
    expect(api.savePayloadDraft).toHaveBeenCalledTimes(1);
    await post({ a: 2 });
    await post({ a: 1 });
    await passDebounce();
    expect(api.savePayloadDraft).toHaveBeenCalledTimes(1);
    expect(q('[data-payload-light]').getAttribute('aria-label')).toBe('saved');
  });

  it('the save disk saves now when pressed, without waiting out the debounce', async () => {
    await open();
    await ready();
    await post({ a: 1 });
    expect(api.savePayloadDraft).not.toHaveBeenCalled();
    expect(q<HTMLButtonElement>('[data-payload-light]').disabled).toBe(false);
    await click('[data-payload-light]');
    expect(api.savePayloadDraft).toHaveBeenCalledTimes(1);
    expect(api.savePayloadDraft).toHaveBeenCalledWith('20261013-bottom-bar', { revision: 'r3', payload: { a: 1 } }, false);
    expect(q('[data-payload-light]').getAttribute('data-draft-state')).toBe('saved');
  });

  it('the save disk reads saving while the write is in flight', async () => {
    let finish: (v: unknown) => void = () => {};
    api.savePayloadDraft.mockReturnValueOnce(new Promise((resolve) => { finish = resolve; }));
    await open();
    await ready();
    await post({ a: 1 });
    await click('[data-payload-light]');
    expect(q('[data-payload-light]').getAttribute('data-draft-state')).toBe('saving');
    expect(q('[data-payload-light]').getAttribute('aria-label')).toBe('saving');
    expect(q('[data-payload-light]').dataset.notesLight).toBe('pending');
    finish({ revision: 'r3', draft: { at: 'x' }, etag: 'e', changed: true });
    await settle();
    expect(q('[data-payload-light]').getAttribute('data-draft-state')).toBe('saved');
  });

  it('the save disk is the retry after a refused write', async () => {
    api.savePayloadDraft.mockRejectedValueOnce(new Error('nope'));
    await open();
    await ready();
    await post({ a: 1 });
    await passDebounce();
    expect(q('[data-payload-light]').getAttribute('data-draft-state')).toBe('failed');
    await click('[data-payload-light]');
    expect(api.savePayloadDraft).toHaveBeenCalledTimes(2);
    expect(q('[data-payload-light]').getAttribute('data-draft-state')).toBe('saved');
  });
});

describe('reopening the board', () => {
  it('hands the autosaved draft to the page (a plain object) and names it in the stepper', async () => {
    api.fetchBoard.mockResolvedValue(payloadBoard({ at: '2026-10-14T09:00:00Z', payload: { milk: false, eggs: 9 } }));
    await open();
    const spy = vi.spyOn(frame().contentWindow!, 'postMessage');
    await ready();
    expect(spy).toHaveBeenCalledWith({ rb: 1, type: 'load', payload: { milk: false, eggs: 9 }, save: null }, '*');
    expect(q('[data-payload-position]').textContent).toBe('draft');
    expect(q('[data-payload-light]').getAttribute('data-draft-state')).toBe('saved');
    expect(q<HTMLButtonElement>('[data-payload-send]').disabled).toBe(false);
  });

  it('falls back to the newest save when there is no draft, and names it', async () => {
    await open();
    const spy = vi.spyOn(frame().contentWindow!, 'postMessage');
    await ready();
    expect(spy).toHaveBeenCalledWith({ rb: 1, type: 'load', payload: SAVES[2]!.payload, save: 3 }, '*');
    expect(q('[data-payload-position]').textContent).toBe('save 3 of 3');
  });

  it('names the save when the draft equals the newest save', async () => {
    api.fetchBoard.mockResolvedValue(payloadBoard({ at: '2026-10-14T09:00:00Z', payload: { eggs: 2, milk: true } }));
    await open();
    await ready();
    expect(q('[data-payload-position]').textContent).toBe('save 3 of 3');
  });
});

describe('the save stepper walks the numbered saves and the draft', () => {
  it('steps back through the saves, one step past the newest returns to the draft, and never rewrites the draft by stepping', async () => {
    api.fetchBoard.mockResolvedValue(payloadBoard({ at: '2026-10-14T09:00:00Z', payload: { milk: false, eggs: 9 } }));
    await open();
    const spy = vi.spyOn(frame().contentWindow!, 'postMessage');
    await ready();
    await click('[data-payload-older]');
    expect(q('[data-payload-position]').textContent).toBe('save 3 of 3');
    await click('[data-payload-older]');
    expect(q('[data-payload-position]').textContent).toBe('save 2 of 3');
    expect(spy).toHaveBeenLastCalledWith({ rb: 1, type: 'load', payload: SAVES[1]!.payload, save: 2 }, '*');
    expect(q('[data-payload-save-note]')?.textContent).toBe('milk yes');
    await post(SAVES[1]!.payload);
    await passDebounce();
    expect(api.savePayloadDraft).not.toHaveBeenCalled();
    await click('[data-payload-newer]');
    await click('[data-payload-newer]');
    expect(q('[data-payload-position]').textContent).toBe('draft');
    expect(spy).toHaveBeenLastCalledWith({ rb: 1, type: 'load', payload: { milk: false, eggs: 9 }, save: null }, '*');
    expect(q<HTMLButtonElement>('[data-payload-newer]').disabled).toBe(true);
  });

  it('an edit made while looking at an older save becomes the draft', async () => {
    await open();
    await ready();
    await click('[data-payload-older]');
    await quiet();
    await post({ milk: 'changed' });
    expect(q('[data-payload-position]').textContent).toBe('draft');
    await passDebounce();
    expect(api.savePayloadDraft.mock.calls[0]![1].payload).toEqual({ milk: 'changed' });
  });
});

describe('Send is the owner\'s click alone', () => {
  it('drops every message that tries to save or send, and a payload alone sends nothing', async () => {
    await open();
    await ready();
    for (const type of ['save', 'send', 'rb.save', 'rb.send', 'round', 'draft']) await fromFrame({ rb: 1, type, payload: { milk: true }, note: 'x' });
    await post({ milk: true });
    await passDebounce();
    expect(api.sendRoundKept).not.toHaveBeenCalled();
  });

  it('hears nothing from another window', async () => {
    await open();
    window.dispatchEvent(new MessageEvent('message', { source: window, origin: 'null', data: { rb: 1, type: 'payload', payload: { milk: true } } }));
    await settle();
    expect(q<HTMLButtonElement>('[data-payload-send]').disabled).toBe(true);
  });

  it('has nothing to send until the page shares a state, then Send wakes up', async () => {
    api.fetchBoard.mockResolvedValue(boardAnswer({ revisions: [revision(1), revision(2), revision(3, { prompts: [], anchors: [], payload_mode: true })] }));
    await open();
    await ready();
    expect(q<HTMLButtonElement>('[data-payload-send]').disabled).toBe(true);
    expect(q('[data-payload-waiting]')).not.toBeNull();
    await post({ milk: true });
    expect(q<HTMLButtonElement>('[data-payload-send]').disabled).toBe(false);
    expect(q('[data-payload-waiting]')).toBeNull();
  });

  it('a click posts the round with the payload and the note under one round id, then names the task', async () => {
    await open();
    await ready();
    await post({ milk: true });
    await click('[data-payload-note-key]');
    const note = q<HTMLTextAreaElement>('[data-payload-note]');
    note.value = 'look at my changes and direct me';
    note.dispatchEvent(new Event('input', { bubbles: true }));
    await settle();
    expect(api.sendRoundKept).not.toHaveBeenCalled();
    await click('[data-payload-send]');
    expect(api.sendRoundKept).toHaveBeenCalledTimes(1);
    expect(q('[data-payload-note-pop]')).toBeNull();
    const [slug, body] = api.sendRoundKept.mock.calls[0]!;
    expect(slug).toBe('20261013-bottom-bar');
    expect(body).toMatchObject({ client_round_id: '11111111-1111-4111-8111-111111111111', revision: 'r3', answers: [], anchor_notes: [], note: 'look at my changes and direct me', payload: { milk: true } });
    expect(q('[data-confirm]')?.textContent).toContain('posted on');
    expect(api.fetchBoard.mock.calls.length).toBeGreaterThan(1);
  });

  it('a failed send keeps the state and the note, and the retry reuses the same round id', async () => {
    api.sendRoundKept.mockRejectedValueOnce(new Error('network'));
    await open();
    await ready();
    await post({ milk: true });
    await click('[data-payload-send]');
    expect(q('[data-payload-failed]')).not.toBeNull();
    await click('[data-payload-send]');
    expect(api.sendRoundKept).toHaveBeenCalledTimes(2);
    expect(api.sendRoundKept.mock.calls[0]![1].client_round_id).toBe(api.sendRoundKept.mock.calls[1]![1].client_round_id);
    expect(q('[data-payload-failed]')).toBeNull();
  });
});

describe('the theme picker repaints only the page frame', () => {
  it('lists the shipped themes, first entry follows the app, and the frame gets the app theme tokens when the page loads', async () => {
    await open();
    const spy = vi.spyOn(frame().contentWindow!, 'postMessage');
    await ready();
    const options = [...document.querySelectorAll('[data-theme-picker] option')].map((o) => o.textContent);
    expect(options).toEqual(['app theme (Carnivore)', 'Carnivore', 'Dracula', 'Matrix']);
    expect(spy).toHaveBeenCalledWith({ rb: 1, type: 'theme', id: 'carnivore', vars: TOKENS.carnivore }, '*');
  });

  it('a chosen theme sends that theme\'s resolved tokens to the frame, is remembered per device, and changes nothing around the page', async () => {
    await open();
    await ready();
    const spy = vi.spyOn(frame().contentWindow!, 'postMessage');
    const picker = q<HTMLSelectElement>('[data-theme-picker]');
    picker.value = 'dracula';
    picker.dispatchEvent(new Event('change', { bubbles: true }));
    await settle();
    expect(spy).toHaveBeenLastCalledWith({ rb: 1, type: 'theme', id: 'dracula', vars: TOKENS.dracula }, '*');
    expect(localStorage.getItem('carnivore.reviewboard.theme')).toBe('dracula');
    expect(document.documentElement.getAttribute('data-session-theme')).toBeNull();
    picker.value = 'matrix';
    picker.dispatchEvent(new Event('change', { bubbles: true }));
    await settle();
    expect(spy).toHaveBeenLastCalledWith({ rb: 1, type: 'theme', id: 'matrix', vars: { '--oc-orange': 'rgb(1, 2, 3)' } }, '*');
    expect(spy.mock.calls.filter((c) => (c[0] as { type: string }).type === 'theme')).toHaveLength(2);
  });

  it('reopens on the remembered theme, and choosing the first entry follows the app again', async () => {
    localStorage.setItem('carnivore.reviewboard.theme', 'dracula');
    await open();
    const spy = vi.spyOn(frame().contentWindow!, 'postMessage');
    await ready();
    expect(q<HTMLSelectElement>('[data-theme-picker]').value).toBe('dracula');
    expect(spy).toHaveBeenCalledWith({ rb: 1, type: 'theme', id: 'dracula', vars: TOKENS.dracula }, '*');
    const picker = q<HTMLSelectElement>('[data-theme-picker]');
    picker.value = '';
    picker.dispatchEvent(new Event('change', { bubbles: true }));
    await settle();
    expect(localStorage.getItem('carnivore.reviewboard.theme')).toBeNull();
    expect(spy).toHaveBeenLastCalledWith({ rb: 1, type: 'theme', id: 'carnivore', vars: TOKENS.carnivore }, '*');
  });
});

describe('the theme picker lists every registered theme source', () => {
  const options = (): string[] => [...document.querySelectorAll('[data-theme-picker] option')].map((o) => o.textContent ?? '');

  it('shows a flat list while only the app registry has themes', async () => {
    await open();
    expect(options()).toEqual(['app theme (Carnivore)', 'Carnivore', 'Dracula', 'Matrix']);
    expect(document.querySelector('[data-theme-picker] optgroup')).toBeNull();
  });

  it('groups by source once a second source offers themes, and paints the frame with that source\'s palette', async () => {
    const remove = registerThemeSource({ id: 'mine', label: 'my themes', list: () => [{ id: 'mine-1', name: 'Mine One' }], tokens: (id) => (id === 'mine-1' ? { '--oc-orange': 'rgb(9, 9, 9)' } : null) });
    try {
      await open();
      await ready();
      const groups = [...document.querySelectorAll('[data-theme-picker] optgroup')].map((g) => g.getAttribute('label'));
      expect(groups).toEqual(['carnivore themes', 'my themes']);
      expect(options()).toContain('Mine One');
      const spy = vi.spyOn(frame().contentWindow!, 'postMessage');
      const select = q<HTMLSelectElement>('[data-theme-picker]');
      select.value = 'mine-1';
      select.dispatchEvent(new Event('change', { bubbles: true }));
      await settle();
      expect(spy).toHaveBeenCalledWith({ rb: 1, type: 'theme', id: 'mine-1', vars: { '--oc-orange': 'rgb(9, 9, 9)' } }, '*');
    } finally {
      remove();
    }
  });

  it('leaves a source with no themes out of the picker', async () => {
    const remove = registerThemeSource({ id: 'empty', label: 'nothing yet', list: () => [], tokens: () => null });
    try {
      await open();
      expect(document.querySelector('[data-theme-picker] optgroup')).toBeNull();
    } finally {
      remove();
    }
  });
});
