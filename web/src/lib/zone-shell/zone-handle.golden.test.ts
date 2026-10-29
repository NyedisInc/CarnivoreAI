/** @vitest-environment jsdom */
import { flushSync, mount, unmount } from 'svelte';
import { expect, test } from 'vitest';
import BarVisibilityDemo from '../../style-guide/specimens/BarVisibilityDemo.svelte';
import { setLocale } from '../i18n/index.svelte';
import { matchGolden } from './fixtures/golden';

setLocale('en');

test('the specimen handles are unchanged (golden)', () => {
  const target = document.createElement('div');
  document.body.appendChild(target);
  const app = mount(BarVisibilityDemo, { target });
  flushSync();
  expect(target.querySelectorAll('[data-bar-handle]')).toHaveLength(2);
  matchGolden('handle.demo.side', target.querySelector('.sg-bv__side'));
  matchGolden('handle.demo.bottom', target.querySelector('.sg-bv__bottom'));
  unmount(app);
  target.remove();
});
