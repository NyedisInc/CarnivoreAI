/** @vitest-environment jsdom */
import { afterEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';
import { createSentFlash, SENT_FLASH_MS, submitLook } from './task-submit-state.svelte';

describe('submitLook (pure)', () => {
  test('idle without text, ready with text, sent while flashing (outranks ready)', () => {
    expect(submitLook(false, false)).toBe('idle');
    expect(submitLook(true, false)).toBe('ready');
    expect(submitLook(false, true)).toBe('sent');
    expect(submitLook(true, true)).toBe('sent');
  });
});

describe('createSentFlash', () => {
  afterEach(() => vi.useRealTimers());

  test('turns on for SENT_FLASH_MS, restarts when flashed again, and stops on demand', () => {
    vi.useFakeTimers();
    const sent = createSentFlash();
    expect(sent.on).toBe(false);
    sent.flash();
    expect(sent.on).toBe(true);
    vi.advanceTimersByTime(SENT_FLASH_MS - 100);
    sent.flash();
    vi.advanceTimersByTime(SENT_FLASH_MS - 100);
    expect(sent.on).toBe(true);
    vi.advanceTimersByTime(200);
    expect(sent.on).toBe(false);
    sent.flash();
    sent.stop();
    expect(sent.on).toBe(false);
  });
});

const calls = vi.hoisted(() => ({ posts: 0 }));
vi.mock('./huddle.svelte', async (importOriginal) => {
  const real = await importOriginal<typeof import('./huddle.svelte')>();
  return { ...real, reply: async () => { calls.posts += 1; return true; } };
});

describe('the reply button', () => {
  let app: Record<string, unknown> | null = null;
  afterEach(() => {
    if (app) unmount(app);
    app = null;
    document.body.innerHTML = '';
  });

  test('idle, then confirm-coloured with text, then "sent" after Enter, then reset', async () => {
    const { default: HuddleThread } = await import('./HuddleThread.svelte');
    const host = document.createElement('div');
    document.body.appendChild(host);
    const item = { id: 5, list: 'all', thread: [] } as never;
    app = mount(HuddleThread, { target: host, props: { item } });
    const btn = host.querySelector<HTMLButtonElement>('.hdt-send')!;
    const box = host.querySelector<HTMLTextAreaElement>('[data-huddle-reply]')!;
    expect(btn.dataset.taskManagerSubmitLook).toBe('idle');
    expect(btn.classList.contains('oc-btn--confirm')).toBe(false);
    box.value = 'hello';
    box.dispatchEvent(new Event('input', { bubbles: true }));
    flushSync();
    expect(btn.dataset.taskManagerSubmitLook).toBe('ready');
    expect(btn.classList.contains('oc-btn--confirm')).toBe(true);
    vi.useFakeTimers();
    box.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true, cancelable: true }));
    await vi.advanceTimersByTimeAsync(10);
    flushSync();
    expect(calls.posts).toBe(1);
    expect(btn.dataset.taskManagerSubmitLook).toBe('sent');
    expect(btn.textContent).toBe('sent');
    expect(btn.classList.contains('oc-btn--confirm')).toBe(true);
    await vi.advanceTimersByTimeAsync(SENT_FLASH_MS + 50);
    flushSync();
    await tick();
    expect(btn.dataset.taskManagerSubmitLook).toBe('idle');
    expect(btn.classList.contains('oc-btn--confirm')).toBe(false);
    vi.useRealTimers();
  }, 30_000);
});
