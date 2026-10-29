/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test } from 'vitest';
import { createRawSnippet, flushSync, mount, unmount } from 'svelte';

import CellFrame from './CellFrame.svelte';
import { META, metaFor } from '../engine/meta';
import { homeLayout } from '../engine/layout.svelte';
import type { SlotId } from '../engine/types';
import { inputFocus } from '../lib/input-focus.svelte';

const SLOT_A = 'terminal:ses_pf_a' as SlotId;
const SLOT_B = 'terminal:ses_pf_b' as SlotId;
const NOTES = 'notes' as SlotId;

function frame(slot: SlotId): { app: object; el: HTMLElement } {
  const target = document.createElement('div');
  document.body.appendChild(target);
  const app = mount(CellFrame, {
    target,
    props: {
      meta: metaFor(slot, META),
      instance: slot,
      widthState: '',
      heightState: '',
      store: homeLayout,
      body: createRawSnippet(() => ({ render: () => '<p>body</p>' })),
    },
  });
  flushSync();
  return { app, el: target.querySelector('.oc-frame') as HTMLElement };
}

beforeEach(() => {
  (globalThis as { ResizeObserver?: unknown }).ResizeObserver = class {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
  };
  homeLayout.add('terminal', 'ses_pf_a');
  homeLayout.add('terminal', 'ses_pf_b');
});

afterEach(() => {
  inputFocus.forget(SLOT_A);
  inputFocus.forget(SLOT_B);
  inputFocus.release(NOTES);
  homeLayout.resetAll();
  document.body.innerHTML = '';
  localStorage.clear();
});

describe('terminal cells: accent border on all, popup focus on the active one', () => {
  test('every terminal cell is marked for the accent border, and nothing else is', () => {
    const a = frame(SLOT_A);
    const b = frame(SLOT_B);
    const notes = frame(NOTES);
    expect(a.el.classList.contains('oc-frame-terminal')).toBe(true);
    expect(b.el.classList.contains('oc-frame-terminal')).toBe(true);
    expect(notes.el.classList.contains('oc-frame-terminal')).toBe(false);
    expect(document.querySelectorAll('.oc-frame.popup-focus')).toHaveLength(0);
    unmount(a.app);
    unmount(b.app);
    unmount(notes.app);
  });

  test('exactly one terminal is active, and it follows the input record', () => {
    const a = frame(SLOT_A);
    const b = frame(SLOT_B);

    inputFocus.claim(SLOT_A);
    flushSync();
    expect(a.el.classList.contains('popup-focus')).toBe(true);
    expect(b.el.classList.contains('popup-focus')).toBe(false);
    expect(document.querySelectorAll('.oc-frame.popup-focus')).toHaveLength(1);

    inputFocus.claim(SLOT_B);
    flushSync();
    expect(a.el.classList.contains('popup-focus')).toBe(false);
    expect(b.el.classList.contains('popup-focus')).toBe(true);
    expect(document.querySelectorAll('.oc-frame.popup-focus')).toHaveLength(1);

    inputFocus.release(SLOT_B);
    flushSync();
    expect(b.el.classList.contains('popup-focus')).toBe(true);
    expect(document.querySelectorAll('.oc-frame.popup-focus')).toHaveLength(1);

    inputFocus.claim(NOTES);
    flushSync();
    expect(document.querySelectorAll('.oc-frame.popup-focus')).toHaveLength(0);
    inputFocus.release(NOTES);

    inputFocus.forget(SLOT_B);
    flushSync();
    expect(document.querySelectorAll('.oc-frame.popup-focus')).toHaveLength(0);
    unmount(a.app);
    unmount(b.app);
  });

  test('a focused non-terminal cell keeps its own ring and never wears the terminal look', () => {
    const notes = frame(NOTES);
    inputFocus.claim(NOTES);
    flushSync();
    expect(notes.el.hasAttribute('data-oc-focus')).toBe(true);
    expect(notes.el.classList.contains('popup-focus')).toBe(false);
    unmount(notes.app);
  });
});
