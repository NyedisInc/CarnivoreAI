/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';
import type { LinkRow } from './links-api';

const net = vi.hoisted(() => ({ authFetch: vi.fn(), cplugEnabled: vi.fn() }));
vi.mock('../sdk', async (importOriginal) => ({ ...(await importOriginal<typeof import('../sdk')>()), ...net }));

import { ApiError, boardHeaderKeys } from '../sdk';
import { resetBoardHeaderKeys } from '../sdk/board-header-keys';
import { publicboardCplug } from './index';
import ShareLinkModal from './ShareLinkModal.svelte';

const SECRET = 'pbl_AAAAAAAAAAAAAAAAAAAAAA.BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB';
const HOST = 'review.home.sugamele.com';
const row = (over: Partial<LinkRow> = {}): LinkRow => ({
  id: 'AAAAAAAAAAAAAAAAAAAAAA', board: 'nav', revision: 'r2', mode: 'pinned', created_at: 1_793_000_000, expires_at: 1_793_086_400, revoked_at: null, status: 'active', ...over,
});

let links: LinkRow[];
let mintError: ApiError | null;
let app: ReturnType<typeof mount> | null = null;
const copied: string[] = [];

function serve(path: string, init?: RequestInit): unknown {
  const method = init?.method ?? 'GET';
  if (path === '/cplugs/publicboard') return { settings: { hostnames: HOST } };
  if (method === 'POST') {
    if (mintError) throw mintError;
    links = [row(), ...links];
    return { token: SECRET, link: row() };
  }
  if (method === 'DELETE' && path.includes('?board=')) {
    links = links.map((l) => ({ ...l, status: 'revoked' as const, revoked_at: 1_793_000_100 }));
    return { revoked: 1 };
  }
  if (method === 'DELETE') {
    links = links.filter((l) => `/cplugs/publicboard/links/${l.id}` !== path);
    return { revoked: 1 };
  }
  return { links };
}

async function settle(): Promise<void> {
  for (let i = 0; i < 6; i += 1) {
    await Promise.resolve();
    await tick();
    flushSync();
  }
}
const q = <T extends Element = HTMLElement>(sel: string): T | null => document.querySelector<T>(sel);
const press = async (sel: string): Promise<void> => { q(sel)!.click(); await settle(); };

async function openWindow(): Promise<void> {
  app = mount(ShareLinkModal, { target: document.body, props: { slug: 'nav', close: () => { if (app) unmount(app); app = null; } } });
  await settle();
}

beforeEach(() => {
  links = [];
  mintError = null;
  copied.length = 0;
  net.authFetch.mockReset();
  net.authFetch.mockImplementation(async (path: string, init?: RequestInit) => serve(path, init));
  Object.assign(globalThis.navigator, { clipboard: { writeText: async (text: string) => { copied.push(text); } } });
});

afterEach(() => {
  if (app) unmount(app);
  app = null;
  document.body.innerHTML = '';
  resetBoardHeaderKeys();
  delete (globalThis as { CopyCompat?: unknown }).CopyCompat;
  vi.restoreAllMocks();
});

describe('the header key', () => {
  it('is absent while the plugin is off and present while it is on', () => {
    publicboardCplug.start?.();
    net.cplugEnabled.mockReturnValue(false);
    expect(boardHeaderKeys()).toEqual([]);
    net.cplugEnabled.mockReturnValue(true);
    expect(boardHeaderKeys().map((k) => k.id)).toEqual(['publicboard.share']);
  });
});

describe('making a link', () => {
  it('shows the whole link once with a copy key, and the copy puts it on the clipboard', async () => {
    await openWindow();
    await press('[data-share-create]');
    const url = q<HTMLInputElement>('[data-share-url]')!;
    expect(url.value).toBe(`https://${HOST}/#${SECRET}`);
    expect(q('[data-share-once]')).not.toBeNull();
    await press('[data-share-copy]');
    expect(copied).toEqual([`https://${HOST}/#${SECRET}`]);
    expect(net.authFetch).toHaveBeenCalledWith('/cplugs/publicboard/links', { method: 'POST', body: JSON.stringify({ board: 'nav', ttl: '1d', mode: 'pinned' }) });
  });

  it('sends the chosen lifetime and mode', async () => {
    await openWindow();
    q<HTMLInputElement>('input[type=radio][value="7d"]')!.click();
    q<HTMLInputElement>('input[type=radio][value="follow"]')!.click();
    await settle();
    await press('[data-share-create]');
    const post = net.authFetch.mock.calls.find((c) => (c[1] as RequestInit | undefined)?.method === 'POST')!;
    expect(JSON.parse((post[1] as RequestInit).body as string)).toEqual({ board: 'nav', ttl: '7d', mode: 'follow' });
  });

  it('never shows the link again after the window closes: the reopened list has the row and no secret', async () => {
    await openWindow();
    await press('[data-share-create]');
    await press('[data-share-close]');
    expect(document.body.textContent).not.toContain('BBBBBBBB');
    await openWindow();
    expect(q('[data-share-url]')).toBeNull();
    expect(q(`[data-share-row="${row().id}"]`)).not.toBeNull();
    expect(document.body.textContent).not.toContain('BBBBBBBB');
    expect(q(`[data-share-row="${row().id}"]`)!.textContent).toContain('active');
  });

  it('lists the new link in the same window right after the mint (the list is read again)', async () => {
    await openWindow();
    expect(document.querySelectorAll('[data-share-row]')).toHaveLength(0);
    await press('[data-share-create]');
    expect(document.querySelectorAll('[data-share-row]')).toHaveLength(1);
    const lists = net.authFetch.mock.calls.filter((c) => String(c[0]).startsWith('/cplugs/publicboard/links?board='));
    expect(lists.length).toBeGreaterThanOrEqual(2);
  });

  it('"make another" clears the shown link and brings the form back', async () => {
    await openWindow();
    await press('[data-share-create]');
    expect(q('[data-share-url]')).not.toBeNull();
    await press('[data-share-another]');
    expect(q('[data-share-url]')).toBeNull();
    expect(q('[data-share-once]')).toBeNull();
    expect(q('[data-share-create]')).not.toBeNull();
    expect(document.body.textContent).not.toContain('BBBBBBBB');
  });

  it('says to select it by hand when the copy ladder reports a failure, and not "copied"', async () => {
    (globalThis as { CopyCompat?: unknown }).CopyCompat = { copyText: async () => ({ ok: false }) };
    await openWindow();
    await press('[data-share-create]');
    await press('[data-share-copy]');
    expect(q('[data-share-notice]')!.textContent).toBe('the copy did not land. select the link and copy it by hand.');
    expect(q('[data-share-copy]')!.textContent).not.toContain('copied');
  });

  it('keeps the token out of storage and the console', async () => {
    const setItem = vi.spyOn(Storage.prototype, 'setItem');
    const spies = (['log', 'info', 'warn', 'error', 'debug'] as const).map((m) => vi.spyOn(console, m).mockImplementation(() => {}));
    await openWindow();
    await press('[data-share-create]');
    expect(setItem).not.toHaveBeenCalled();
    for (const spy of spies) expect(JSON.stringify(spy.mock.calls)).not.toContain('BBBBBBBB');
  });

  it('disables making and says why when no host name is set', async () => {
    net.authFetch.mockImplementation(async (path: string, init?: RequestInit) => (path === '/cplugs/publicboard' ? { settings: {} } : serve(path, init)));
    await openWindow();
    expect(q('[data-share-no-host]')).not.toBeNull();
    expect(q<HTMLButtonElement>('[data-share-create]')!.disabled).toBe(true);
  });
});

describe('removing a link', () => {
  it('calls DELETE on the id and the row goes', async () => {
    links = [row()];
    await openWindow();
    await press(`[data-share-remove="${row().id}"]`);
    expect(net.authFetch).toHaveBeenCalledWith(`/cplugs/publicboard/links/${row().id}`, { method: 'DELETE' });
    expect(q(`[data-share-row="${row().id}"]`)).toBeNull();
  });

  it('offers no remove key on a link that has ended', async () => {
    links = [row({ status: 'revoked', revoked_at: 1_793_000_100 })];
    await openWindow();
    expect(q(`[data-share-row="${row().id}"]`)).not.toBeNull();
    expect(q('[data-share-remove]')).toBeNull();
  });
});

describe('removing every link of the board', () => {
  it('asks first, then calls DELETE on the board and the live rows end', async () => {
    links = [row(), row({ id: 'CCCCCCCCCCCCCCCCCCCCCC' })];
    await openWindow();
    await press('[data-share-remove-all]');
    expect(net.authFetch).not.toHaveBeenCalledWith('/cplugs/publicboard/links?board=nav', { method: 'DELETE' });
    await press('[data-share-remove-all-go]');
    expect(net.authFetch).toHaveBeenCalledWith('/cplugs/publicboard/links?board=nav', { method: 'DELETE' });
    expect(q('[data-share-remove]')).toBeNull();
    expect(q('[data-share-remove-all]')).toBeNull();
  });

  it('is not offered when no link is live', async () => {
    links = [row({ status: 'expired' })];
    await openWindow();
    expect(q('[data-share-remove-all]')).toBeNull();
  });
});

describe('refusals', () => {
  it('names the detectors of a credential refusal, never a value', async () => {
    mintError = new ApiError('x', 422, 'publicboard_has_secret', { detail: { code: 'publicboard_has_secret', detectors: { aws_key: 1 } } });
    await openWindow();
    await press('[data-share-create]');
    expect(q('[data-share-notice]')!.textContent).toBe('the board holds what looks like a credential (aws_key), so it was not shared.');
    expect(q('[data-share-url]')).toBeNull();
  });

  it('says an api key cannot do this on a 403', async () => {
    mintError = new ApiError('forbidden', 403);
    await openWindow();
    await press('[data-share-create]');
    expect(q('[data-share-notice]')!.textContent).toBe('an api key cannot make or end public links. use the app.');
  });

  it('shows the server reason on a 409', async () => {
    mintError = new ApiError('the review board plugin is off, so there is nothing to share', 409, 'publicboard_no_reviewboard');
    await openWindow();
    await press('[data-share-create]');
    expect(q('[data-share-notice]')!.textContent).toBe('the review board plugin is off, so there is nothing to share');
  });
});
