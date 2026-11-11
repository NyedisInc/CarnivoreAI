/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';
import PublicBoard from './PublicBoard.svelte';
import type { AnswerSet, DraftResult, PostBody, PostResult, PostRoute, PublicBoardData } from './board-client';
import { newPostId, postToBoard } from './board-client';

const BOARD: PublicBoardData = {
  title: 'bottom bar', revision: 'r1', frame_ttl: 300, viewport: 320, views: [{ id: 'main', label: 'main', frame: '/f/t' }],
  prompts: [
    { id: 'layout', kind: 'choice', label: 'which row', options: [{ id: 'a', label: 'one' }, { id: 'b', label: 'two' }] },
    { id: 'padding', kind: 'check', label: 'padding ok', options: [] },
    { id: 'extra', kind: 'question', label: 'anything missing?', options: [] },
  ],
  anchors: [{ id: 'send', label: 'send button' }],
};

let app: ReturnType<typeof mount> | null = null;
let posts: Array<{ route: PostRoute; body: PostBody }>;
let saves: Array<{ revision: string } & AnswerSet>;
let answer: PostResult;

async function settle(): Promise<void> {
  for (let i = 0; i < 6; i += 1) { await Promise.resolve(); await tick(); flushSync(); }
}

async function open(): Promise<void> {
  const send = async (route: PostRoute, body: PostBody): Promise<PostResult> => { posts.push({ route, body }); return answer; };
  const save = async (body: { revision: string } & AnswerSet): Promise<DraftResult> => { saves.push(body); return { kind: 'saved', changed: true }; };
  app = mount(PublicBoard, { target: document.body, props: { load: async () => ({ kind: 'board', board: { ...BOARD, access: 'answer' } }), send, save } });
  await settle();
}

function typeInto(el: HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement, value: string): void {
  el.value = value;
  el.dispatchEvent(new Event(el instanceof HTMLSelectElement ? 'change' : 'input', { bubbles: true }));
  flushSync();
}

function choose(name: string, index: number): void {
  const input = document.querySelectorAll<HTMLInputElement>(`input[name="pbf-${name}"]`)[index]!;
  input.checked = true;
  input.dispatchEvent(new Event('change', { bubbles: true }));
  flushSync();
}

function openComment(): void {
  document.querySelector<HTMLButtonElement>('[data-visitor-key="comment"]')!.click();
  flushSync();
}

const said = (): string | null | undefined => document.querySelector('[data-visitor-said]')?.textContent;

beforeEach(() => {
  posts = [];
  saves = [];
  answer = { kind: 'received', duplicate: false };
  vi.stubGlobal('ResizeObserver', class { observe(): void {} unobserve(): void {} disconnect(): void {} });
});
afterEach(() => { if (app) unmount(app); app = null; document.body.innerHTML = ''; vi.useRealTimers(); vi.unstubAllGlobals(); });

describe('answers', () => {
  it('have no send key: the page draws none for the questions and none for a layer', async () => {
    await open();
    expect(document.querySelector('[data-visitor-send-answers], [data-visitor-send-page]')).toBeNull();
    expect(document.body.textContent).not.toMatch(/send answers/);
  });

  it('save themselves: a pick autosaves the answers in the server\'s shape after the quiet time, and nothing is posted', async () => {
    vi.useFakeTimers();
    await open();
    choose('layout', 1);
    choose('padding', 1);
    await vi.advanceTimersByTimeAsync(2000);
    expect(saves.at(-1)).toEqual({ revision: 'r1', answers: [{ prompt: 'layout', options: ['b'] }, { prompt: 'padding', checked: false }] });
    expect(posts).toEqual([]);
    vi.useRealTimers();
  });
});

describe('a comment', () => {
  it('points at a declared spot, and a retry after a refusal reuses the same key so it lands once', async () => {
    await open();
    openComment();
    typeInto(document.querySelector<HTMLTextAreaElement>('#pbf-comment')!, 'too close to the edge');
    typeInto(document.querySelector<HTMLSelectElement>('[data-visitor-anchor]')!, 'send');
    answer = { kind: 'state', state: 'limited' };
    document.querySelector<HTMLButtonElement>('[data-visitor-send-comment]')!.click();
    await settle();
    expect(said()).toBe('too many requests. wait a minute and try again.');
    answer = { kind: 'received', duplicate: false };
    document.querySelector<HTMLButtonElement>('[data-visitor-send-comment]')!.click();
    await settle();
    expect(posts.map((p) => p.body)).toEqual([
      { client_post_id: posts[0]!.body.client_post_id, text: 'too close to the edge', anchor: 'send', revision: BOARD.revision },
      { client_post_id: posts[0]!.body.client_post_id, text: 'too close to the edge', anchor: 'send', revision: BOARD.revision },
    ]);
    expect(document.querySelector<HTMLTextAreaElement>('#pbf-comment')!.value).toBe('');
  });

  it('tells the visitor a credential was refused, in plain words', async () => {
    await open();
    openComment();
    typeInto(document.querySelector<HTMLTextAreaElement>('#pbf-comment')!, 'key ghp_xxx');
    answer = { kind: 'state', state: 'has_secret' };
    document.querySelector<HTMLButtonElement>('[data-visitor-send-comment]')!.click();
    await settle();
    expect(said()).toBe('that looks like it holds a password or a key, so it was not sent. remove it and try again.');
  });
});

describe('the post call', () => {
  it('sends the secret only in the header, posts JSON to the exact route, and reads the state', async () => {
    const seen: Array<{ url: string; init: RequestInit }> = [];
    const fetcher = async (url: string, init: RequestInit): Promise<Response> => {
      seen.push({ url, init });
      return new Response(JSON.stringify({ state: 'rejected' }), { status: 422 });
    };
    const out = await postToBoard('pbl_secret', 'comments', { client_post_id: 'abcdefgh', text: 'hi' }, fetcher);
    expect(out).toEqual({ kind: 'state', state: 'rejected' });
    expect(seen[0]!.url).toBe('/api/comments');
    expect(seen[0]!.init.method).toBe('POST');
    expect((seen[0]!.init.headers as Record<string, string>)['Carnivore-Board-Link']).toBe('pbl_secret');
    expect(seen[0]!.init.credentials).toBe('omit');
    expect(String(seen[0]!.init.body)).not.toContain('pbl_secret');
  });
});

describe('the post id (L3)', () => {
  it('falls back to getRandomValues where randomUUID is missing (plain http is not a secure context)', () => {
    const id = newPostId({ getRandomValues: <T extends ArrayBufferView | null>(a: T): T => { (a as unknown as Uint8Array).fill(171); return a; } });
    expect(id).toBe('ab'.repeat(16));
    expect(id).toMatch(/^[A-Za-z0-9_-]{8,64}$/);
  });

  it('sends a post with an id even when randomUUID is missing', async () => {
    vi.stubGlobal('crypto', { getRandomValues: (a: Uint8Array) => a.fill(1) });
    await open();
    openComment();
    typeInto(document.querySelector<HTMLTextAreaElement>('#pbf-comment')!, 'hello');
    document.querySelector<HTMLButtonElement>('[data-visitor-send-comment]')!.click();
    await settle();
    expect(posts[0]!.body.client_post_id).toBe('01'.repeat(16));
  });
});
