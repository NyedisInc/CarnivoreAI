/** @vitest-environment jsdom */
import { afterEach, describe, expect, test, vi } from 'vitest';
import { createRawSnippet, mount, unmount } from 'svelte';
import ModalShell from './ModalShell.svelte';

let app: ReturnType<typeof mount> | null = null;

afterEach(() => {
  if (app) unmount(app);
  app = null;
  document.body.innerHTML = '';
});

function open(props: { trapFocus?: boolean; escapeGuard?: (event: KeyboardEvent) => boolean; onCancel: () => void; width?: string; height?: string; fill?: boolean }): HTMLElement {
  const children = createRawSnippet(() => ({ render: () => '<div><input id="a" /><button id="b" type="button">b</button></div>' }));
  app = mount(ModalShell, { target: document.body.appendChild(document.createElement('div')), props: { title: 'x', children, ...props } });
  return document.querySelector<HTMLElement>('.modal-overlay')!;
}

function press(el: Element, key: string, shiftKey = false): KeyboardEvent {
  const event = new KeyboardEvent('keydown', { key, shiftKey, bubbles: true, cancelable: true });
  el.dispatchEvent(event);
  return event;
}

describe('ModalShell terminal keys', () => {
  test('by default Tab wraps inside the dialog and Escape cancels', () => {
    const onCancel = vi.fn();
    const overlay = open({ onCancel });
    const last = overlay.querySelector<HTMLElement>('.modal-body button')!;
    last.focus();
    expect(press(last, 'Tab').defaultPrevented).toBe(true);
    press(last, 'Escape');
    expect(onCancel).toHaveBeenCalledTimes(1);
  });

  test('trapFocus false leaves Tab to the inside', () => {
    const overlay = open({ trapFocus: false, onCancel: vi.fn() });
    const last = [...overlay.querySelectorAll<HTMLElement>('.modal-body button')].at(-1)!;
    last.focus();
    expect(press(last, 'Tab').defaultPrevented).toBe(false);
  });

  test('an escapeGuard answering false keeps the dialog open and still stops the key', () => {
    const onCancel = vi.fn();
    const seen = vi.fn();
    document.body.addEventListener('keydown', seen);
    const overlay = open({ escapeGuard: () => false, onCancel });
    press(overlay.querySelector('input')!, 'Escape');
    expect(onCancel).not.toHaveBeenCalled();
    expect(seen).not.toHaveBeenCalled();
    document.body.removeEventListener('keydown', seen);
  });

  test('an escapeGuard answering true cancels', () => {
    const onCancel = vi.fn();
    const overlay = open({ escapeGuard: () => true, onCancel });
    press(overlay.querySelector('input')!, 'Escape');
    expect(onCancel).toHaveBeenCalledTimes(1);
  });

  test('width, height and fill land on the panel itself, inline, and lift the chassis max width', () => {
    const overlay = open({ width: '700px', height: '400px', fill: true, onCancel: vi.fn() });
    const panel = overlay.querySelector<HTMLElement>('.modal-content')!;
    expect([panel.style.width, panel.style.height, panel.style.maxWidth]).toEqual(['700px', '400px', 'none']);
    expect(panel.classList.contains('modal-content--fill')).toBe(true);
  });

  test('no size leaves the plain panel alone', () => {
    const panel = open({ onCancel: vi.fn() }).querySelector<HTMLElement>('.modal-content')!;
    expect([panel.style.width, panel.style.maxWidth]).toEqual(['', '']);
    expect(panel.classList.contains('modal-content--fill')).toBe(false);
  });
});
