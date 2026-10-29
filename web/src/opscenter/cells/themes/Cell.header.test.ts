/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

import Cell from './Cell.svelte';
import { metaFor } from '../../engine/meta';
import { themesCellView } from './view.svelte';
import type { ThemeManifest } from '../../api/types';

function manifest(id: string, name: string): ThemeManifest {
  return {
    id,
    name,
    description: '',
    author: null,
    version: null,
    cssVars: { '--color-bg-page': '#0d0a13', '--color-accent': '#bf9bff' },
    xterm: {},
    source: 'builtin',
  };
}

const THEMES = [manifest('nord', 'nord'), manifest('matrix', 'matrix')];

const CURRENT: { rows: ThemeManifest[] | null; status: string } = {
  rows: THEMES,
  status: 'ok',
};

vi.mock('../../api', async () => {
  const actual = await vi.importActual<Record<string, unknown>>('../../api');
  return {
    ...actual,
    themes: {
      get data() {
        return CURRENT.rows;
      },
      get status() {
        return CURRENT.status;
      },
      get error() {
        return null;
      },
    },
    sessions: {
      get data() {
        return null;
      },
      get status() {
        return 'ok';
      },
    },
    openThemes: () => true,
  };
});

beforeEach(() => {
  CURRENT.rows = THEMES;
  CURRENT.status = 'ok';
  themesCellView.set('favorites');
});

afterEach(() => {
  document.body.innerHTML = '';
});

function render() {
  const target = document.createElement('div');
  document.body.appendChild(target);
  const component = mount(Cell, {
    target,
    props: { width: 400, height: 300, meta: metaFor('themes'), instance: 'themes' },
  });
  flushSync();
  return { target, component };
}

describe('the ascii decoration selector is gone from this cell', () => {
  test('no select and no "ascii decoration" text anywhere in the mount', () => {
    const { target, component } = render();
    expect(target.querySelector('select')).toBe(null);
    expect(target.textContent ?? '').not.toContain('ascii decoration');
    unmount(component);
  });
});

describe('the header toggle', () => {
  test('is the only button of its kind, pressed for the default favorites view, and carries a catalog label', () => {
    const { target, component } = render();
    const buttons = target.querySelectorAll('.oc-themes-toggle button');
    expect(buttons.length).toBe(1);
    const button = buttons[0] as HTMLButtonElement;
    expect(button.getAttribute('aria-pressed')).toBe('true');
    expect(button.getAttribute('aria-label')).toBe('show favorites only');
    expect(button.querySelector('svg[data-icon="star"]')).not.toBe(null);
    unmount(component);
  });

  test('clicking it flips aria-pressed and the list filter, in both directions', () => {
    const { target, component } = render();
    expect(target.querySelector('[data-themes-notice]')).not.toBe(null);
    expect(target.querySelector('.oc-tile-grid')).toBe(null);

    const button = target.querySelector('.oc-themes-toggle button') as HTMLButtonElement;
    button.click();
    flushSync();

    expect(button.getAttribute('aria-pressed')).toBe('false');
    expect(button.getAttribute('aria-label')).toBe('show favorites only');
    expect(themesCellView.value).toBe('all');
    expect(target.querySelector('[data-themes-notice]')).toBe(null);
    expect(target.querySelectorAll('[data-tile]').length).toBe(THEMES.length);

    button.click();
    flushSync();

    expect(button.getAttribute('aria-pressed')).toBe('true');
    expect(themesCellView.value).toBe('favorites');
    expect(target.querySelector('.oc-tile-grid')).toBe(null);
    unmount(component);
  });
});
