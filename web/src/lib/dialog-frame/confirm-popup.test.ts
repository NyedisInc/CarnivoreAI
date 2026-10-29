/** @vitest-environment jsdom */
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';
import ConfirmPopup from './ConfirmPopup.svelte';

let app: ReturnType<typeof mount> | null = null;
let anchor: HTMLButtonElement;

beforeEach(() => {
  anchor = document.createElement('button');
  document.body.append(anchor);
  anchor.focus();
});
afterEach(() => {
  if (app) unmount(app);
  app = null;
  document.body.replaceChildren();
});

function ask(props: Record<string, unknown> = {}): HTMLElement {
  app = mount(ConfirmPopup, {
    target: document.body,
    props: { label: 'clear board', message: 'clear every note?', anchor, cancelLabel: 'cancel', confirmLabel: 'clear', onConfirm: () => {}, onCancel: () => {}, ...props },
  });
  flushSync();
  return document.querySelector<HTMLElement>('[role="alertdialog"]')!;
}

test('it is an alertdialog on the shared popup frame with the question and two buttons in the shared family', () => {
  const pop = ask({ 'data-mine': '' });
  expect(pop.getAttribute('aria-label')).toBe('clear board');
  expect([...pop.classList]).toEqual(expect.arrayContaining(['oc-anchored', 'popup-focus', 'oc-confirm-popup']));
  expect(pop.hasAttribute('data-mine')).toBe(true);
  expect(pop.textContent).toContain('clear every note?');
  expect(pop.querySelector('[data-btn="secondary"]')?.textContent).toBe('cancel');
  expect(pop.querySelector('[data-btn="danger"]')?.textContent).toBe('clear');
});

test('focus starts on the safe button, not the destructive one', () => {
  const pop = ask();
  expect(document.activeElement).toBe(pop.querySelector('[data-confirm-cancel]'));
});

test('the destructive button confirms, the quiet one cancels, and the host hooks land on each', () => {
  const onConfirm = vi.fn();
  const onCancel = vi.fn();
  const pop = ask({ onConfirm, onCancel, confirmProps: { 'data-go': '' }, cancelProps: { 'data-no': '' } });
  pop.querySelector<HTMLButtonElement>('[data-go]')!.click();
  expect(onConfirm).toHaveBeenCalledTimes(1);
  pop.querySelector<HTMLButtonElement>('[data-no]')!.click();
  expect(onCancel).toHaveBeenCalledTimes(1);
});

test('Escape and a press outside answer no; a press on the key does not', () => {
  const onCancel = vi.fn();
  const pop = ask({ onCancel });
  pop.querySelector('[data-confirm-cancel]')!.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
  expect(onCancel).toHaveBeenCalledTimes(1);
  anchor.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true }));
  expect(onCancel).toHaveBeenCalledTimes(1);
  document.body.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true }));
  expect(onCancel).toHaveBeenCalledTimes(2);
});

test('while busy the destructive button is disabled and Escape is held', () => {
  const onCancel = vi.fn();
  const pop = ask({ busy: true, onCancel });
  expect(pop.querySelector<HTMLButtonElement>('[data-confirm-go]')!.disabled).toBe(true);
  pop.querySelector('[data-confirm-cancel]')!.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
  expect(onCancel).not.toHaveBeenCalled();
});

test('focus goes back to the key when the question closes', () => {
  ask();
  unmount(app!);
  app = null;
  expect(document.activeElement).toBe(anchor);
});
