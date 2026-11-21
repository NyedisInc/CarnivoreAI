/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { flushSync, tick } from 'svelte';
import { startPage } from './start';
import { openBoard } from './session';
import type { Fetcher } from './board-client';
import { LINK_HEADER } from './fragment';

const tokenOf = (c: string): string => `pbl_${c.repeat(22)}.${c.repeat(43)}`;
const A = tokenOf('A');
const B = tokenOf('B');

function server(): { fetcher: Fetcher; seen: string[] } {
  const seen: string[] = [];
  const fetcher: Fetcher = async (url, init) => {
    if (url === '/api/next') return new Response('{"state":"fixed"}', { status: 200 });
    const token = (init.headers as Record<string, string>)[LINK_HEADER] ?? '';
    seen.push(token);
    const letter = token.charAt(4);
    if (letter === 'E') return new Response('{"state":"ended"}', { status: 404 });
    if (letter === 'I') return new Response('{"state":"invalid"}', { status: 404 });
    if (letter === 'L') return new Response('{"state":"limited"}', { status: 429 });
    return new Response(JSON.stringify({ title: `board ${letter}`, revision: 'r1', views: [{ id: 'main', label: 'main', frame: `/f/${letter}` }] }), { status: 200 });
  };
  return { fetcher, seen };
}

async function settle(): Promise<void> {
  for (let i = 0; i < 6; i += 1) { await Promise.resolve(); await tick(); flushSync(); }
}

let stop: (() => void) | null = null;
beforeEach(() => {
  window.sessionStorage.clear();
  document.body.innerHTML = '<div id="board"><p class="pb-note">loading. static fallback</p></div>';
  vi.stubGlobal('ResizeObserver', class { observe(): void {} unobserve(): void {} disconnect(): void {} });
});
afterEach(() => { stop?.(); stop = null; vi.unstubAllGlobals(); });

describe('openBoard forgets a dead link', () => {
  it.each([['E', 'ended'], ['I', 'invalid']])('an %s link (%s) is not kept for the next reload', async (letter) => {
    const token = tokenOf(letter as string);
    window.history.replaceState(null, '', `/#${token}`);
    const { fetcher } = server();
    expect(await openBoard(window, fetcher)).toMatchObject({ kind: 'state' });
    expect(window.sessionStorage.getItem('publicboard.link')).toBeNull();
  });
  it('keeps the secret through a rate limit or a server fault, which say nothing about the link', async () => {
    const token = tokenOf('L');
    window.history.replaceState(null, '', `/#${token}`);
    await openBoard(window, server().fetcher);
    expect(window.sessionStorage.getItem('publicboard.link')).toBe(token);
  });
  it('keeps the secret of a live link', async () => {
    window.history.replaceState(null, '', `/#${A}`);
    expect(await openBoard(window, server().fetcher)).toMatchObject({ kind: 'board' });
    expect(window.sessionStorage.getItem('publicboard.link')).toBe(A);
  });
});

describe('startPage', () => {
  it('clears the static fallback, strips the address and draws the first board', async () => {
    window.history.replaceState(null, '', `/#${A}`);
    const { fetcher } = server();
    stop = startPage(window, document.getElementById('board')!, fetcher);
    await settle();
    expect(document.body.textContent).not.toContain('static fallback');
    expect(document.querySelector('.pb-title')?.textContent).toBe('board A');
    expect(window.location.hash).toBe('');
  });

  it('a second link pasted into the same tab is stripped, asked for with its own secret, and shown', async () => {
    window.history.replaceState(null, '', `/#${A}`);
    const { fetcher, seen } = server();
    stop = startPage(window, document.getElementById('board')!, fetcher);
    await settle();
    expect(document.querySelector('.pb-title')?.textContent).toBe('board A');

    const changed = new Promise<void>((done) => window.addEventListener('hashchange', () => done(), { once: true }));
    window.location.hash = B;
    await changed;
    await settle();

    expect(seen).toEqual([A, B]);
    expect(document.querySelector('.pb-title')?.textContent).toBe('board B');
    expect(document.querySelectorAll('main').length).toBe(1);
    expect(window.location.hash).toBe('');
    expect(window.location.href).not.toContain(B);
    expect(window.sessionStorage.getItem('publicboard.link')).toBe(B);
    expect(JSON.stringify(Object.entries(window.localStorage))).not.toContain(B);
  });

  it('our own removal of the fragment is not a new link and asks nothing more', async () => {
    window.history.replaceState(null, '', `/#${A}`);
    const { fetcher, seen } = server();
    stop = startPage(window, document.getElementById('board')!, fetcher);
    await settle();
    window.dispatchEvent(new HashChangeEvent('hashchange'));
    await settle();
    expect(seen).toEqual([A]);
  });

  it('a second link that has ended shows its state in place of the first board', async () => {
    window.history.replaceState(null, '', `/#${A}`);
    stop = startPage(window, document.getElementById('board')!, server().fetcher);
    await settle();
    const changed = new Promise<void>((done) => window.addEventListener('hashchange', () => done(), { once: true }));
    window.location.hash = tokenOf('E');
    await changed;
    await settle();
    expect(document.querySelector('.pb-note--state')?.getAttribute('data-state')).toBe('ended');
    expect(document.querySelector('.pb-title')?.textContent).not.toBe('board A');
    expect(window.sessionStorage.getItem('publicboard.link')).toBeNull();
  });

  it('stop removes the listener, so a later fragment does nothing', async () => {
    window.history.replaceState(null, '', `/#${A}`);
    const { fetcher, seen } = server();
    stop = startPage(window, document.getElementById('board')!, fetcher);
    await settle();
    stop();
    stop = null;
    const changed = new Promise<void>((done) => window.addEventListener('hashchange', () => done(), { once: true }));
    window.location.hash = B;
    await changed;
    await settle();
    expect(seen).toEqual([A]);
  });
});
