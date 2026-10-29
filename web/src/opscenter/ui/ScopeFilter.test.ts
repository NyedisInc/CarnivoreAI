/** @vitest-environment jsdom */
import { afterEach, describe, expect, test } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';
import ScopeFilter from './ScopeFilter.svelte';
import { DEFAULT_SCOPE, inScope, readScope, writeScope, type Scope } from './scope-filter';
import { setLocale } from '../../lib/i18n/index.svelte';

setLocale('en');

const apps: ReturnType<typeof mount>[] = [];
afterEach(() => {
  for (const app of apps.splice(0)) unmount(app);
  document.body.innerHTML = '';
  globalThis.localStorage?.clear();
});

describe('the scope filter', () => {
  test('draws global, sessions and both with the value checked, and reports a click', () => {
    const picked: Scope[] = [];
    const target = document.createElement('div');
    document.body.appendChild(target);
    apps.push(mount(ScopeFilter, { target, props: { value: 'global', onChange: (s: Scope) => picked.push(s), label: 'show' } }));
    flushSync();
    const items = [...target.querySelectorAll('[role="radio"]')];
    expect(items.map((el) => el.textContent?.trim())).toEqual(['global', 'sessions', 'both']);
    expect(items.map((el) => el.getAttribute('aria-checked'))).toEqual(['true', 'false', 'false']);
    expect(target.querySelector('[role="radiogroup"]')?.getAttribute('aria-label')).toBe('show');
    (target.querySelector('[data-scope="sessions"]') as HTMLElement).click();
    expect(picked).toEqual(['sessions']);
  });

  test('a row passes when the filter is its kind or both', () => {
    expect(inScope('global', 'global')).toBe(true);
    expect(inScope('global', 'sessions')).toBe(false);
    expect(inScope('sessions', 'both')).toBe(true);
  });

  test('a surface remembers its choice; nothing stored reads both', () => {
    expect(readScope('t-surface')).toBe(DEFAULT_SCOPE);
    writeScope('t-surface', 'sessions');
    expect(readScope('t-surface')).toBe('sessions');
    expect(readScope('another')).toBe('both');
  });
});
