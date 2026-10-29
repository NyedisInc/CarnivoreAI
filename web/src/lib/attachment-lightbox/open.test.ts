/** @vitest-environment jsdom */
import { afterEach, expect, test, vi } from 'vitest';
import { flushSync } from 'svelte';
import { closeAttachmentLightbox, openAttachmentLightbox, ATTACHMENT_LIGHTBOX_ID } from './open';
import { setLocale } from '../i18n/index.svelte';

setLocale('en');

afterEach(() => {
  closeAttachmentLightbox();
  document.body.innerHTML = '';
  vi.restoreAllMocks();
});

test('opens full size from the blob, Esc closes it and focus returns to the thumbnail', () => {
  const create = vi.fn(() => 'blob:full-1');
  const revoke = vi.fn();
  Object.assign(URL, { createObjectURL: create, revokeObjectURL: revoke });
  const thumb = document.createElement('button');
  document.body.appendChild(thumb);

  const blob = new Blob(['x'], { type: 'image/png' });
  expect(openAttachmentLightbox(blob, 'shot.png', thumb)).toBe(true);
  flushSync();

  const img = document.querySelector<HTMLImageElement>(`#${ATTACHMENT_LIGHTBOX_ID} img`);
  expect(img?.getAttribute('src')).toBe('blob:full-1');
  expect(img?.getAttribute('alt')).toBe('shot.png');
  expect(create).toHaveBeenCalledWith(blob);

  window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }));
  flushSync();
  expect(document.querySelector(`#${ATTACHMENT_LIGHTBOX_ID} img`)).toBeNull();
  expect(revoke).toHaveBeenCalledWith('blob:full-1');
  expect(document.activeElement).toBe(thumb);
});
