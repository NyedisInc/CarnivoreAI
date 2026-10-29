/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

import Cell from './Cell.svelte';
import { metaFor } from '../../engine/meta';
import { installPopoverPolyfill } from '../../../lib/popover-jsdom-polyfill';

installPopoverPolyfill();

const startSessionInProject = vi.fn(() => true);
const startNewProject = vi.fn(() => true);

vi.mock('../../api', async () => {
  const actual = await vi.importActual<Record<string, unknown>>('../../api');
  return {
    ...actual,
    sessions: {
      get data() {
        return [];
      },
      get status() {
        return 'ok';
      },
      get error() {
        return null;
      },
    },
    projects: {
      get data() {
        return [];
      },
      get status() {
        return 'ok';
      },
    },
    startSessionInProject: () => startSessionInProject(),
    startNewProject: () => startNewProject(),
  };
});

beforeEach(() => {
  startSessionInProject.mockClear();
  startNewProject.mockClear();
});

afterEach(() => {
  document.body.innerHTML = '';
});

function render() {
  const target = document.createElement('div');
  document.body.appendChild(target);
  const component = mount(Cell, {
    target,
    props: { width: 400, height: 300, meta: metaFor('running-sessions'), instance: 'running-sessions' },
  });
  flushSync();
  return { target, component };
}

describe('the "+" button', () => {
  test('renders once, with a catalog label, and opens a two row menu', () => {
    const { target, component } = render();
    const buttons = target.querySelectorAll('button[data-oc-new]');
    expect(buttons.length).toBe(1);

    const button = buttons[0] as HTMLButtonElement;
    expect(button.getAttribute('aria-label')).toBe('start a new session or project');
    expect(button.getAttribute('aria-expanded')).toBe('false');

    button.click();
    flushSync();

    expect(button.getAttribute('aria-expanded')).toBe('true');
    const items = document.body.querySelectorAll('[role="menuitem"]');
    expect(items.length).toBe(2);
    expect(items[0]?.querySelector('.acm-label')?.textContent?.trim()).toBe('new session');
    expect(items[1]?.querySelector('.acm-label')?.textContent?.trim()).toBe('new project');

    unmount(component);
  });

  test('"new session" runs the existing session-in-a-project flow, and nothing else', () => {
    const { target, component } = render();
    (target.querySelector('button[data-oc-new]') as HTMLButtonElement).click();
    flushSync();

    (document.body.querySelector('[role="menuitem"]') as HTMLButtonElement).click();
    flushSync();

    expect(startSessionInProject).toHaveBeenCalledTimes(1);
    expect(startNewProject).not.toHaveBeenCalled();
    unmount(component);
  });

  test('"new project" runs the existing new-claude-project flow, and nothing else', () => {
    const { target, component } = render();
    (target.querySelector('button[data-oc-new]') as HTMLButtonElement).click();
    flushSync();

    const items = document.body.querySelectorAll('[role="menuitem"]');
    (items[1] as HTMLButtonElement).click();
    flushSync();

    expect(startNewProject).toHaveBeenCalledTimes(1);
    expect(startSessionInProject).not.toHaveBeenCalled();
    unmount(component);
  });
});
