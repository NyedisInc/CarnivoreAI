/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';
import type { VisitorResponse } from './visitors-api';

const net = vi.hoisted(() => ({ authFetch: vi.fn(), cplugEnabled: vi.fn() }));
vi.mock('../../sdk', async (importOriginal) => ({ ...(await importOriginal<typeof import('../../sdk')>()), ...net, cplugSetting: () => true }));

import { boardHeaderKeys } from '../board-header-keys';
import { registerVisitorRevisionOpener, resetVisitorRevisions, type VisitorRevision } from '../board-visitor-revisions.svelte';
import { resetBoardHeaderKeys } from '../board-header-keys';
import { reviewboardPopout } from '../popout'; // the plugin alone: its pop-out part registers the board keys
import VisitorsModal from './VisitorsModal.svelte';

const XSS = '<img src=x onerror="window.__pwned=1"><script>window.__pwned=2</script>';
const rows = (): VisitorResponse[] => [
  { id: 1, revision: 'r1', kind: 'comment', name: '<b onmouseover=alert(1)>sam</b>', created_at: 1_793_000_000, forwarded_at: null,
    entries: [{ label: 'send button', text: XSS }] },
  { id: 2, revision: 'r1', kind: 'answers', name: null, created_at: 1_793_000_100, forwarded_at: 1_793_000_200,
    entries: [{ label: 'which row', picks: ['<i>two</i>'] }, { label: 'padding', checked: false, note: '[link](javascript:alert(1))' }] },
];

let app: ReturnType<typeof mount> | null = null;
let calls: Array<{ path: string; method: string; body?: unknown }>;

async function settle(): Promise<void> {
  for (let i = 0; i < 6; i += 1) { await Promise.resolve(); await tick(); flushSync(); }
}

async function openWindow(): Promise<void> {
  app = mount(VisitorsModal, { target: document.body, props: { slug: 'nav', close: () => { if (app) unmount(app); app = null; } } });
  await settle();
}

beforeEach(() => {
  calls = [];
  net.authFetch.mockImplementation(async (path: string, init?: RequestInit) => {
    calls.push({ path, method: init?.method ?? 'GET', ...(init?.body ? { body: JSON.parse(String(init.body)) } : {}) });
    if (init?.method === 'POST') return { forwarded: 1, left: 0, messages: 1, message_id: 7, item_id: 526 };
    if (init?.method === 'DELETE') return { removed: 1 };
    return { responses: rows() };
  });
  net.cplugEnabled.mockReturnValue(true);
  (window as unknown as { __pwned?: number }).__pwned = undefined;
});
afterEach(() => { if (app) unmount(app); app = null; document.body.innerHTML = ''; vi.clearAllMocks(); resetBoardHeaderKeys(); resetVisitorRevisions(); });

describe('the visitors window', () => {
  it('draws a visitor\'s markup as literal text and creates no element from it', async () => {
    await openWindow();
    const modal = document.querySelector('[data-board-visitors-modal]') ?? document.body;
    expect(modal.textContent).toContain(`send button: ${XSS}`);
    expect(modal.textContent).toContain('which row: <i>two</i>');
    expect(modal.textContent).toContain('note: [link](javascript:alert(1))');
    expect(document.querySelectorAll('img, script, b, i, a[href]').length).toBe(0);
    expect((window as unknown as { __pwned?: number }).__pwned).toBeUndefined();
  });

  it('labels every sender unverified, named or not', async () => {
    await openWindow();
    const who = [...document.querySelectorAll('.pbs-vwho')].map((n) => n.textContent);
    expect(who).toEqual(['visitor (unverified): <b onmouseover=alert(1)>sam</b>', 'visitor (unverified)']);
  });

  it('only reads on open; forwarding happens on the owner\'s press alone', async () => {
    await openWindow();
    expect(calls).toEqual([{ path: '/cplugs/reviewboard/public/visitors?board=nav', method: 'GET' }]);
    document.querySelector<HTMLButtonElement>('[data-visitors-forward]')!.click();
    await settle();
    expect(calls.filter((c) => c.method === 'POST')).toEqual([{ path: '/cplugs/reviewboard/public/visitors/forward', method: 'POST', body: { board: 'nav', ids: [1] } }]);
    expect(document.querySelector('[data-visitors-notice]')?.textContent).toBe('forwarded 1. replies posted: 1.');
  });

  it('cannot forward when nothing is new', async () => {
    net.authFetch.mockImplementation(async () => ({ responses: rows().map((r) => ({ ...r, forwarded_at: 1 })) }));
    await openWindow();
    expect(document.querySelector<HTMLButtonElement>('[data-visitors-forward]')!.disabled).toBe(true);
  });
});

describe('the look-alike warning', () => {
  it('tells the owner visitor text can hold look-alike letters, to read before forwarding', async () => {
    await openWindow();
    expect(document.querySelector('[data-visitors-lookalike]')?.textContent).toBe(
      'visitor text can contain look-alike letters, such as a cyrillic a that reads as a latin a. read it before you forward it.');
  });
});

describe('removing (M3)', () => {
  it('removes one response from its own danger key, and the forwarded ones only after the confirm popup', async () => {
    await openWindow();
    document.querySelector<HTMLButtonElement>('[data-visitor-remove="2"]')!.click();
    await settle();
    expect(calls.filter((c) => c.method === 'DELETE').map((c) => c.path)).toEqual(['/cplugs/reviewboard/public/visitors/2']);
    document.querySelector<HTMLButtonElement>('[data-visitors-remove-forwarded]')!.click();
    await settle();
    expect(calls.filter((c) => c.method === 'DELETE')).toHaveLength(1);
    document.querySelector<HTMLButtonElement>('[data-visitors-remove-forwarded-go]')!.click();
    await settle();
    expect(calls.filter((c) => c.method === 'DELETE').map((c) => c.path)).toEqual(['/cplugs/reviewboard/public/visitors/2', '/cplugs/reviewboard/public/visitors?board=nav']);
  });
});

describe('the header key', () => {
  it('is contributed while the plugin is on and withdrawn when it is off', () => {
    reviewboardPopout.start?.();
    expect(boardHeaderKeys().map((k) => k.id)).toContain('reviewboard.visitors');
    net.cplugEnabled.mockReturnValue(false);
    expect(boardHeaderKeys().map((k) => k.id)).not.toContain('reviewboard.visitors');
  });
});

describe('who answered (slice 5)', () => {
  const U1: VisitorRevision = { label: 'u1', number: 1, revision: 'r1', updated_at: 1_793_000_300 };

  it('lists each visitor\'s u revision and opens it on the board page through the seam, closing the window', async () => {
    net.authFetch.mockImplementation(async () => ({ responses: rows(), visitors: [U1] }));
    const opened: Array<[string, string, number]> = [];
    registerVisitorRevisionOpener((slug, revision, number) => opened.push([slug, revision, number]));
    await openWindow();
    const row = document.querySelector<HTMLButtonElement>('[data-visitor-revision="u1"]')!;
    expect(row.textContent).toContain('last edit');
    expect(row.textContent).not.toMatch(/sent/);
    row.click();
    await settle();
    expect(opened).toEqual([['nav', 'r1', 1]]);
    expect(document.querySelector('[data-visitor-revision]')).toBeNull();
  });

  it('cannot open a u revision while no board page is on screen', async () => {
    net.authFetch.mockImplementation(async () => ({ responses: rows(), visitors: [U1] }));
    await openWindow();
    expect(document.querySelector<HTMLButtonElement>('[data-visitor-revision="u1"]')?.disabled).toBe(true);
  });
});

describe('what a forward says (R5-1)', () => {
  it('names the replies posted and, past the ceiling, how many stay for the next forward; it never promises a next forward otherwise', async () => {
    net.authFetch.mockImplementation(async (path: string, init?: RequestInit) => init?.method === 'POST'
      ? { forwarded: 5, left: 2, messages: 3, message_id: 7, item_id: 526 } : { responses: rows() });
    await openWindow();
    document.querySelector<HTMLButtonElement>('[data-visitors-forward]')!.click();
    await settle();
    expect(document.querySelector('[data-visitors-notice]')?.textContent).toBe('forwarded 5. replies posted: 3. 2 did not fit the limit of one click and stay here for the next forward.');
  });
});

describe('forwarding autosaved answers (R4-1)', () => {
  it('is possible with no unforwarded response: a visitor who only answered still has the key enabled, and it names no ids', async () => {
    net.authFetch.mockImplementation(async (path: string, init?: RequestInit) => {
      calls.push({ path, method: init?.method ?? 'GET', ...(init?.body ? { body: JSON.parse(String(init.body)) } : {}) });
      return init?.method === 'POST' ? { forwarded: 1, left: 0, messages: 1, message_id: 7, item_id: 526 }
        : { responses: [], visitors: [{ label: 'u1', number: 1, revision: 'r1', updated_at: 1_793_000_300 }] };
    });
    await openWindow();
    const key = document.querySelector<HTMLButtonElement>('[data-visitors-forward]')!;
    expect(key.disabled).toBe(false);
    key.click();
    await settle();
    expect(calls.find((c) => c.method === 'POST')?.body).toEqual({ board: 'nav', ids: [] });
  });

  it('stays disabled when there is nothing at all', async () => {
    net.authFetch.mockImplementation(async () => ({ responses: [], visitors: [] }));
    await openWindow();
    expect(document.querySelector<HTMLButtonElement>('[data-visitors-forward]')!.disabled).toBe(true);
  });
});

describe('removing a u revision (slice 5 review)', () => {
  it('the remove key drops that u revision through its owner route and reads the list again', async () => {
    const U2: VisitorRevision = { label: 'u2', number: 2, revision: 'r1', updated_at: 1_793_000_300 };
    net.authFetch.mockImplementation(async (path: string, init?: RequestInit) => {
      calls.push({ path, method: init?.method ?? 'GET' });
      return init?.method === 'DELETE' ? { removed: 1 } : { responses: rows(), visitors: [U2] };
    });
    await openWindow();
    (document.querySelector('[data-visitor-revision-remove="u2:r1"]') as HTMLButtonElement).click();
    await settle();
    expect(calls.filter((c) => c.method === 'DELETE')).toEqual([{ path: '/cplugs/reviewboard/public/visitors/u/2?board=nav&revision=r1', method: 'DELETE' }]);
    expect(calls.filter((c) => c.method === 'GET').length).toBeGreaterThan(1);
  });
});
