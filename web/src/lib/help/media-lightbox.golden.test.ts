/** @vitest-environment jsdom */
import { afterEach, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';
import MediaLightbox from './MediaLightbox.svelte';
import { setLocale } from '../i18n/index.svelte';
import { recorded, snapshot } from '../dialog-frame/goldens';

setLocale('en');

let app: ReturnType<typeof mount> | null = null;
afterEach(() => {
  if (app) unmount(app);
  app = null;
  document.body.innerHTML = '';
});

test('the window renders its recorded markup', () => {
  localStorage.clear();
  Object.assign(window, { innerWidth: 1000, innerHeight: 800 });
  app = mount(MediaLightbox, { target: document.body, props: { src: 'blob:x', alt: 'a', caption: 'shot.png', onClose: vi.fn() } });
  flushSync();
  const now = snapshot(document.querySelector('[role="dialog"]')!);
  expect(now).toBe(recorded('media-lightbox', now));
});
