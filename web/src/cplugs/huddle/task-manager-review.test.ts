/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

const server = vi.hoisted(() => ({ items: [] as Record<string, unknown>[] }));

const mk = (id: number, extra: Record<string, unknown>) => ({
  id, list: 'all', text: `item ${id}`, note: '', position: id, created_by: 'claude', state: 'open', kind: '',
  number: id, revision: 1, created_seq: id, seq: id, deleted: false, status: 'open', thread: [],
  unread: false, info_unseen: false, attention_unseen: false, ...extra,
});

vi.mock('../../opscenter/api/auth.svelte', async (importOriginal) => {
  const real = await importOriginal<typeof import('../../opscenter/api/auth.svelte')>();
  return {
    ...real,
    authFetch: async (path: string) => {
      if (path === '/cplugs/huddle') return { revision: 1, settings: { hideCompleted: false } };
      if (path === '/cplugs/huddle/focus') return { focus: null };
      if (path === '/cplugs/huddle/lists') return { cursor: 0, lists: [{ key: 'all', name: null, project_id: null, items: 4, open: 4, review: 0, questions: 0, claude_seq: 0, unread: 0, waiting_to_send: 0 }] };
      if (path.endsWith('/sessions')) return { sessions: [], default: null, reason: 'pick' };
      if (/^\/cplugs\/huddle\/lists\/[^/]+$/.test(path)) return { list: 'all', revision: 7, cursor: 7, items: server.items };
      return {};
    },
  };
});

import { huddle, refreshTaskManager } from './huddle.svelte';
import { linkTarget, reviewOf } from './huddle-review';
import HuddleBody from './HuddleBody.svelte';
import { cplugEnablement } from '../host/enablement.svelte';

cplugEnablement.enabled = { huddle: true };

let app: ReturnType<typeof mount> | null = null;

async function settle(): Promise<void> {
  for (let i = 0; i < 10; i += 1) {
    await Promise.resolve();
    await tick();
  }
  flushSync();
}

async function mountBody(popout = false): Promise<HTMLElement> {
  const host = document.createElement('div');
  document.body.appendChild(host);
  app = mount(HuddleBody, { target: host, props: { popout } });
  await settle();
  return host;
}

const fields = { review_description: 'check the new block', review_where: 'huddle tab, row', review_link: '/#/projects', review_action: 'push' };

beforeEach(async () => {
  server.items = [
    mk(1, { status: 'review', state: 'review', ...fields }),
    mk(2, { status: 'working', ...fields }),
    mk(3, { status: 'review', state: 'review' }),
    mk(4, { status: 'review', state: 'review', review_description: '  ', review_where: null, review_link: '' }),
  ];
  huddle.selected = 'all';
  huddle.addTarget = 'all';
  huddle.openId = null;
  await refreshTaskManager();
});

afterEach(() => {
  window.localStorage.clear();
  if (app) unmount(app);
  app = null;
  document.body.innerHTML = '';
});

describe('the review block', () => {
  test('pure: only in review, only with a field set, blanks trimmed away', () => {
    expect(reviewOf(mk(1, { status: 'review', ...fields }) as never)).toEqual({ action: 'push', summary: 'check the new block', hasMore: false, description: 'check the new block', where: 'huddle tab, row', link: '/#/projects' });
    expect(reviewOf(mk(2, { status: 'working', ...fields }) as never)).toBeNull();
    expect(reviewOf(mk(3, { status: 'review' }) as never)).toBeNull();
    expect(reviewOf(mk(4, { status: 'review', review_link: '/#/x' }) as never)).toEqual({ action: 'tick', summary: '', hasMore: false, description: '', where: '', link: '/#/x' });
    expect(reviewOf(mk(5, { status: 'review', review_where: 'x', review_action: 'bogus' }) as never)?.action).toBe('tick');
  });

  test.each([false, true])('shows under the row WITHOUT opening it, in review only (popout %s)', async (popout) => {
    const host = await mountBody(popout);
    const block = host.querySelector<HTMLElement>('[data-task-manager-review="1"]');
    expect(block).not.toBeNull();
    expect(huddle.openId).toBeNull();
    expect(block!.querySelector('.hb-kind')!.textContent).toBe('review');
    expect(block!.querySelector('[data-task-manager-review-summary]')!.textContent).toContain('check the new block');
    expect(block!.querySelector('[data-task-manager-review-where]')!.textContent).toBe('huddle tab, row');
    expect(block!.textContent).not.toContain('click path');
    const tag = block!.querySelector<HTMLElement>('[data-task-manager-action]')!;
    expect(tag.dataset.taskManagerAction).toBe('push');
    expect(tag.textContent).toBe('check and tick to push');
    expect(block!.querySelector('[data-task-manager-review-part]')!.contains(tag)).toBe(true);
    expect(block!.querySelector('[data-task-manager-review-where]')!.textContent).toContain('huddle tab, row');
    for (const id of [2, 3, 4]) expect(host.querySelector(`[data-task-manager-review="${id}"]`)).toBeNull();
    host.querySelector<HTMLElement>('[data-task-manager-toggle="1"]')!.click();
    await settle();
    expect(host.querySelector('[data-task-manager-review="1"]')).not.toBeNull();
    expect(host.querySelector('[data-task-manager-description="1"]')!.textContent).toBe('item 1');
  });

  test('an app link on this page routes by hash; other links open in a new tab with rel=noopener', async () => {
    const host = await mountBody();
    const link = host.querySelector<HTMLAnchorElement>('[data-task-manager-review="1"] [data-task-manager-review-link]')!;
    expect(link.getAttribute('target')).toBeNull();
    const click = new MouseEvent('click', { bubbles: true, cancelable: true });
    link.dispatchEvent(click);
    expect(click.defaultPrevented).toBe(true);
    expect(window.location.hash).toBe('#/projects');
    const here = { origin: 'http://app.test', pathname: '/' };
    expect(linkTarget('https://example.com/p', here)).toEqual({ kind: 'external', href: 'https://example.com/p', hash: null });
    expect(linkTarget('/session/abc', here)).toEqual({ kind: 'app', href: '/session/abc', hash: null });
    expect(linkTarget('javascript:alert(1)', here)).toBeNull();
    expect(linkTarget('//evil.example/x', here)).toBeNull();
  });

  test('an external link is a new-tab anchor with rel=noopener, and a javascript: link draws none', async () => {
    server.items = [
      mk(1, { status: 'review', review_link: 'https://example.com/pr/1' }),
      mk(2, { status: 'review', review_description: 'x', review_link: 'javascript:alert(1)' }),
    ];
    await refreshTaskManager();
    const host = await mountBody();
    const external = host.querySelector<HTMLAnchorElement>('[data-task-manager-review="1"] a')!;
    expect(external.getAttribute('target')).toBe('_blank');
    expect(external.getAttribute('rel')).toBe('noopener');
    expect(external.getAttribute('href')).toBe('https://example.com/pr/1');
    expect(host.querySelector('[data-task-manager-review="2"] a')).toBeNull();
  });
});

describe('the review description renders markdown', () => {
  test('bold and list items draw as elements, a tag in the text stays literal', async () => {
    server.items = [mk(1, { status: 'review', review_description: '**check** these:\n\n- one\n- two <b>x</b>' })];
    await refreshTaskManager();
    const host = await mountBody();
    host.querySelector<HTMLButtonElement>('[data-task-manager-review="1"] [data-task-manager-review-fold]')!.click();
    await settle();
    const text = host.querySelector<HTMLElement>('[data-task-manager-review="1"] [data-task-manager-review-description]')!;
    expect(text.querySelector('strong')!.textContent).toBe('check');
    expect(text.querySelectorAll('li').length).toBe(2);
    expect(text.querySelector('b')).toBeNull();
    expect(text.textContent).toContain('<b>x</b>');
  });
});
