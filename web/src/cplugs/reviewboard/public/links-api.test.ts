import { beforeEach, describe, expect, it, vi } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const net = vi.hoisted(() => ({ authFetch: vi.fn() }));
vi.mock('../../sdk', async (importOriginal) => ({ ...(await importOriginal<typeof import('../../sdk')>()), ...net }));

import { ApiError } from '../../sdk';
import { ACCESSES, MODES, PALETTE_MAX_BYTES, PALETTE_MAX_VARS, TTLS, fitPalette, linkUrl, listLinks, mintLink, publicHost, refusalReason, revokeBoardLinks, revokeLink } from './links-api';

beforeEach(() => net.authFetch.mockReset());

describe('the calls', () => {
  it('mints with a POST of board, ttl, mode and access (answer by default)', async () => {
    net.authFetch.mockResolvedValue({ token: 'pbl_a.b', link: {} });
    await mintLink('b1', '1d', 'follow');
    expect(net.authFetch).toHaveBeenCalledWith('/cplugs/reviewboard/public/links', { method: 'POST', body: JSON.stringify({ board: 'b1', ttl: '1d', mode: 'follow', access: 'answer' }) });
  });

  it('mints a read only link carrying the owner\'s palette', async () => {
    net.authFetch.mockResolvedValue({ token: 'pbl_a.b', link: {} });
    await mintLink('b1', '1h', 'pinned', 'read', { '--oc-orange': '#f80' });
    expect(net.authFetch).toHaveBeenCalledWith('/cplugs/reviewboard/public/links', {
      method: 'POST', body: JSON.stringify({ board: 'b1', ttl: '1h', mode: 'pinned', access: 'read', theme: { '--oc-orange': '#f80' } }),
    });
  });

  it('lists one board and unwraps links', async () => {
    net.authFetch.mockResolvedValue({ links: [{ id: 'x' }] });
    expect(await listLinks('a b')).toEqual([{ id: 'x' }]);
    expect(net.authFetch).toHaveBeenCalledWith('/cplugs/reviewboard/public/links?board=a%20b');
  });

  it('revokes with a DELETE on the id', async () => {
    net.authFetch.mockResolvedValue({ revoked: 1 });
    await revokeLink('abc');
    expect(net.authFetch).toHaveBeenCalledWith('/cplugs/reviewboard/public/links/abc', { method: 'DELETE' });
  });

  it('reads the first host name, or null when none is set', async () => {
    net.authFetch.mockResolvedValue({ settings: { hostnames: ' review.home.sugamele.com , b.example.com' } });
    expect(await publicHost()).toBe('review.home.sugamele.com');
    net.authFetch.mockResolvedValue({ settings: { hostnames: ' , ,review.home.sugamele.com' } });
    expect(await publicHost()).toBe('review.home.sugamele.com');
    net.authFetch.mockResolvedValue({ settings: { hostnames: ' , ' } });
    expect(await publicHost()).toBeNull();
    net.authFetch.mockResolvedValue({ settings: { hostnames: '' } });
    expect(await publicHost()).toBeNull();
  });

  it('revokes a whole board with a DELETE on ?board= and answers the count', async () => {
    net.authFetch.mockResolvedValue({ revoked: 3 });
    expect(await revokeBoardLinks('b1')).toBe(3);
    expect(net.authFetch).toHaveBeenCalledWith('/cplugs/reviewboard/public/links?board=b1', { method: 'DELETE' });
  });

  it('puts the token in the fragment, never the path or query', () => {
    expect(linkUrl('h.example.com', 'pbl_a.b')).toBe('https://h.example.com/#pbl_a.b');
  });
});

describe('the sentences', () => {
  it('says an api key was refused', () => {
    expect(refusalReason(new ApiError('forbidden', 403))).toBe('an api key cannot make or end public links. use the app.');
  });

  it('names the detectors of a secret refusal and no value', () => {
    const body = { detail: { code: 'publicboard_has_secret', detectors: { aws_key: 2, github_token: 1 } } };
    const text = refusalReason(new ApiError('x', 422, 'publicboard_has_secret', body));
    expect(text).toBe('the board holds what looks like a credential (aws_key, github_token), so it was not shared.');
  });

  it('shows the server reason lowercase for a 409 and a scan timeout', () => {
    expect(refusalReason(new ApiError('The review board plugin is off', 409, 'publicboard_no_reviewboard'))).toBe('the review board plugin is off');
    expect(refusalReason(new ApiError('public links are unavailable: source_busy', 503, 'public_links_unavailable'))).toBe('public links are unavailable: source_busy');
  });

  it('has a plain sentence for anything that is not an api error', () => {
    expect(refusalReason(new TypeError('boom'))).toBe('the link could not be made. try again.');
  });
});

describe('no second list of lifetimes and modes', () => {
  const source = readFileSync(resolve(__dirname, '../../../../../src/cplugs/reviewboard/public/links.py'), 'utf8');
  const literal = (name: string): string[] => {
    const hit = new RegExp(`^${name} = Literal\\[([^\\]]+)\\]`, 'm').exec(source);
    return (hit?.[1] ?? '').split(',').map((s) => s.trim().replace(/"/g, ''));
  };

  it('matches links.py Ttl', () => expect([...TTLS]).toEqual(literal('Ttl')));
  it('matches links.py Mode', () => expect([...MODES]).toEqual(literal('Mode')));
  it('matches links.py Access', () => expect([...ACCESSES]).toEqual(literal('Access')));
});

describe('the palette sent with a link (slice 5 review)', () => {
  it('keeps at most the frame\'s count of --oc- tokens, in order, and nothing else', () => {
    const vars = Object.fromEntries([['color', 'red'], ...Array.from({ length: 700 }, (_, n) => [`--oc-t${n}`, '#123456'])]);
    const fitted = fitPalette(vars);
    expect(Object.keys(fitted)).toHaveLength(PALETTE_MAX_VARS);
    expect(Object.keys(fitted)[0]).toBe('--oc-t0');
  });

  it('stops before the frame\'s byte limit', () => {
    const vars = Object.fromEntries(Array.from({ length: 400 }, (_, n) => [`--oc-t${n}`, 'a'.repeat(200)]));
    const size = JSON.stringify(fitPalette(vars)).length;
    expect(size).toBeGreaterThan(0);
    expect(size).toBeLessThanOrEqual(PALETTE_MAX_BYTES);
  });
});
