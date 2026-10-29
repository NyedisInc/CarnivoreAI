/** @vitest-environment jsdom */
import { afterEach, expect, test } from 'vitest';
import { captureOpener, restoreOpenerFocus } from './opener-focus';

afterEach(() => document.body.replaceChildren());

test('captures the focused element and gives focus back to it', () => {
  const button = document.createElement('button');
  const other = document.createElement('input');
  document.body.append(button, other);
  button.focus();
  const opener = captureOpener();
  expect(opener).toBe(button);
  other.focus();
  restoreOpenerFocus(opener);
  expect(document.activeElement).toBe(button);
});

test('a null opener or one removed from the document is left alone', () => {
  const button = document.createElement('button');
  document.body.append(button);
  button.focus();
  const opener = captureOpener();
  button.remove();
  expect(() => restoreOpenerFocus(opener)).not.toThrow();
  expect(() => restoreOpenerFocus(null)).not.toThrow();
  expect(captureOpener()).not.toBeInstanceOf(HTMLButtonElement);
});
