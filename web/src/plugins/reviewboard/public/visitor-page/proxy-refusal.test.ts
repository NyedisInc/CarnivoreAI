/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import type { Fetcher } from './board-client';
import { LINK_HEADER } from './fragment';
import { openBoard, saveDraft, sendPost, waitNext } from './session';

const TOKEN = `pbl_${'A'.repeat(22)}.${'b'.repeat(43)}`;
const PROXY_404 = '<html><head><title>404 Not Found</title></head><body><center><h1>404 Not Found</h1></center><hr><center>openresty</center></body></html>';

function proxy(): { fetcher: Fetcher; secrets: Array<string | undefined> } {
  const secrets: Array<string | undefined> = [];
  const fetcher: Fetcher = async (url, init) => {
    secrets.push((init.headers as Record<string, string>)[LINK_HEADER]);
    if (url === '/api/comments') return new Response('{"state":"received","duplicate":false}', { status: 201 });
    return new Response(PROXY_404, { status: 404, headers: { 'content-type': 'text/html' } });
  };
  return { fetcher, secrets };
}

beforeEach(() => {
  window.sessionStorage.clear();
  window.history.replaceState(null, '', `/#${TOKEN}`);
});
afterEach(() => window.sessionStorage.clear());

describe('an answer that names no state', () => {
  it('a draft refused by the proxy is "cannot be reached", never "not found"', async () => {
    const { fetcher } = proxy();
    expect(await saveDraft(window, { revision: 'r1', answers: [] }, fetcher)).toEqual({ kind: 'state', state: 'unavailable' });
  });

  it('keeps the secret, so the comment sent after the refused draft still carries it and lands', async () => {
    const { fetcher, secrets } = proxy();
    await saveDraft(window, { revision: 'r1', answers: [] }, fetcher);
    const sent = await sendPost(window, 'comments', { client_post_id: 'a'.repeat(32), text: 'hi' }, fetcher);
    expect(sent).toEqual({ kind: 'received', duplicate: false });
    expect(secrets).toEqual([TOKEN, TOKEN]);
  });

  it('a board read and a held wait that meet the proxy page are "cannot be reached" too', async () => {
    const { fetcher } = proxy();
    expect(await openBoard(window, fetcher)).toEqual({ kind: 'state', state: 'unavailable' });
    expect(await waitNext(window, 'r1', fetcher)).toEqual({ kind: 'state', state: 'unavailable' });
    expect(window.sessionStorage.getItem('publicboard.link')).toBe(TOKEN);
  });

  it('a named "invalid" from the server is still a verdict: the secret is forgotten', async () => {
    const fetcher: Fetcher = async () => new Response('{"state":"invalid"}', { status: 404 });
    expect(await saveDraft(window, { revision: 'r1', answers: [] }, fetcher)).toEqual({ kind: 'state', state: 'invalid' });
    expect(window.sessionStorage.getItem('publicboard.link')).toBeNull();
  });
});
