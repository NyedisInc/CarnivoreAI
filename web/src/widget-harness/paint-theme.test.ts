/** @vitest-environment jsdom */
import { afterEach, expect, test, vi } from 'vitest';

import { paintTheme } from './paint-theme';

function stubThemes(themes: Record<string, Record<string, string>>): void {
  vi.stubGlobal('fetch', async (url: string) => {
    const id = Object.keys(themes).find((one) => String(url).includes(`/${one}/`));
    return id
      ? { ok: true, status: 200, json: async () => ({ cssVars: themes[id] }) }
      : { ok: false, status: 404, json: async () => ({}) };
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
  document.documentElement.removeAttribute('style');
});

test('a variable only the first theme sets is gone after the second paint', async () => {
  stubThemes({ one: { '--only-one': 'red', '--both': '1' }, two: { '--both': '2' } });
  await paintTheme('one');
  expect(document.documentElement.style.getPropertyValue('--only-one')).toBe('red');
  await paintTheme('two');
  expect(document.documentElement.style.getPropertyValue('--only-one')).toBe('');
  expect(document.documentElement.style.getPropertyValue('--both')).toBe('2');
});
