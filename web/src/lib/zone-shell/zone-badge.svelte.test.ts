/** @vitest-environment jsdom */
import { afterEach, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';
import ZoneBadge from './ZoneBadge.svelte';

let handle: ReturnType<typeof mount> | null = null;
const props = $state<{ count: number | null; global: boolean }>({ count: null, global: false });

afterEach(() => {
  if (handle) unmount(handle);
  handle = null;
  document.body.innerHTML = '';
  vi.useRealTimers();
});

test('draws a given count, caps it, hides zero and unknown, and pulses only on growth', () => {
  vi.useFakeTimers();
  handle = mount(ZoneBadge, { target: document.body, props: { get count() { return props.count; }, get global() { return props.global; } } });
  flushSync();
  const bubble = (): HTMLElement | null => document.querySelector<HTMLElement>('[data-rail-badge]');
  expect(bubble()).toBeNull();
  props.count = 0;
  flushSync();
  expect(bubble()).toBeNull();
  props.count = 2;
  flushSync();
  expect(bubble()!.textContent).toBe('2');
  expect(bubble()!.dataset['cue'], 'it grew').toBe('on');
  vi.advanceTimersByTime(2000);
  flushSync();
  expect(bubble()!.dataset['cue']).toBeUndefined();
  props.count = 1;
  flushSync();
  expect(bubble()!.dataset['cue'], 'a shrink is quiet').toBeUndefined();
  props.count = 150;
  flushSync();
  expect(bubble()!.textContent).toBe('99+');
  expect(bubble()!.dataset['cue']).toBe('on');
  props.count = null;
  flushSync();
  expect(bubble()).toBeNull();
});

test('the global mark is drawn from the prop and alone, with or without a count', () => {
  props.count = null;
  props.global = true;
  handle = mount(ZoneBadge, { target: document.body, props: { get count() { return props.count; }, get global() { return props.global; } } });
  flushSync();
  expect(document.querySelector('[data-widget-globe]')).not.toBeNull();
  expect(document.querySelector('[data-rail-badge]')).toBeNull();
  props.global = false;
  flushSync();
  expect(document.querySelector('[data-widget-globe]')).toBeNull();
});
