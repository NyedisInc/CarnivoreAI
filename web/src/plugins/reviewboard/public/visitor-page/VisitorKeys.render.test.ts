/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';
import PublicBoard from './PublicBoard.svelte';
import { readFileSync } from 'node:fs';
import catalog from '../../catalog.en.js';
import type { PostBody, PostResult, PostRoute, PublicBoardData } from './board-client';

const BOARD: PublicBoardData = {
  title: 'bottom bar', revision: 'r1', frame_ttl: 300, viewport: 320, views: [{ id: 'main', label: 'main', frame: '/f/t' }],
  prompts: [{ id: 'q', kind: 'question', label: 'anything?', options: [] }],
  anchors: [{ id: 'send', label: 'send button' }],
};
const css = readFileSync(`${process.cwd()}/src/plugins/reviewboard/public/visitor-page/public.css`, 'utf8');
let app: ReturnType<typeof mount> | null = null;
let posts: Array<{ route: PostRoute; body: PostBody }>;

async function settle(): Promise<void> {
  for (let i = 0; i < 6; i += 1) { await Promise.resolve(); await tick(); flushSync(); }
}
async function open(access: 'answer' | 'read', extra: Partial<PublicBoardData> = {}): Promise<void> {
  const send = async (route: PostRoute, body: PostBody): Promise<PostResult> => { posts.push({ route, body }); return { kind: 'received', duplicate: false }; };
  const save = async () => ({ kind: 'saved' as const, changed: true });
  app = mount(PublicBoard, { target: document.body, props: { load: async () => ({ kind: 'board', board: { ...BOARD, ...extra, access } }), send, save } });
  await settle();
}
const key = (which: string): HTMLButtonElement | null => document.querySelector(`[data-visitor-key="${which}"]`);
const bar = (): Element => document.querySelector('[data-visitor-bar]')!;

beforeEach(() => {
  posts = [];
  vi.stubGlobal('ResizeObserver', class { observe(): void {} unobserve(): void {} disconnect(): void {} });
});
afterEach(() => { if (app) unmount(app); app = null; document.body.innerHTML = ''; vi.unstubAllGlobals(); });

describe('the anchored header bar', () => {
  it('is sticky at the top of the page', () => {
    expect(css).toMatch(/\.pb-titlebar\s*\{[^}]*position:\s*sticky;[^}]*top:\s*0;/);
  });

  it('holds the name and comment keys on an answering link, and the body holds neither field', async () => {
    await open('answer');
    expect(bar().contains(key('name'))).toBe(true);
    expect(bar().contains(key('comment'))).toBe(true);
    expect(document.querySelector('#pbf-comment, #pbf-name, [data-visitor-send-comment]')).toBeNull();
  });

  it('draws no keys on a read only link', async () => {
    await open('read');
    expect(bar()).not.toBeNull();
    expect(key('name')).toBeNull();
    expect(key('comment')).toBeNull();
  });

  it('opens a popout in the popup look under the key, and Escape, a press outside and the other key close it', async () => {
    await open('answer');
    key('comment')!.click(); flushSync();
    const pop = document.querySelector('[data-visitor-pop="comment"]')!;
    expect(pop.classList.contains('popup-focus')).toBe(true);
    expect(key('comment')!.getAttribute('aria-expanded')).toBe('true');
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true })); flushSync();
    expect(document.querySelector('[data-visitor-pop]')).toBeNull();
    key('comment')!.click(); flushSync();
    document.body.dispatchEvent(new Event('pointerdown', { bubbles: true })); flushSync();
    expect(document.querySelector('[data-visitor-pop]')).toBeNull();
    key('comment')!.click(); flushSync();
    key('name')!.click(); flushSync();
    expect(document.querySelector('[data-visitor-pop="comment"]')).toBeNull();
    expect(document.querySelector('[data-visitor-pop="name"]')).not.toBeNull();
  });

  it('sends the comment with the name from its popout', async () => {
    await open('answer');
    key('name')!.click(); flushSync();
    const nameBox = document.querySelector<HTMLInputElement>('[data-visitor-name]')!;
    nameBox.value = 'dana'; nameBox.dispatchEvent(new Event('input', { bubbles: true })); flushSync();
    key('comment')!.click(); flushSync();
    const box = document.querySelector<HTMLTextAreaElement>('#pbf-comment')!;
    box.value = 'tighter'; box.dispatchEvent(new Event('input', { bubbles: true })); flushSync();
    document.querySelector<HTMLButtonElement>('[data-visitor-send-comment]')!.click();
    await settle();
    expect(posts).toHaveLength(1);
    expect(posts[0]!.route).toBe('comments');
    expect(posts[0]!.body).toMatchObject({ name: 'dana', text: 'tighter' });
  });

  it('prints its key words from the catalog', async () => {
    await open('answer');
    expect(key('comment')!.getAttribute('aria-label')).toBe(catalog['cplug.reviewboard.public.page.comment_key']);
    expect(key('name')!.getAttribute('aria-label')).toBe(catalog['cplug.reviewboard.public.page.name_key']);
  });
});
