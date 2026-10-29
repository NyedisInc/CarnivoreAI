/** @vitest-environment jsdom */
import { afterEach, describe, expect, test } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';
import WidgetIcon from './WidgetIcon.svelte';
import { isGlobalWidget } from '../widgets/global-scope';

const mounted: Array<Record<string, unknown>> = [];

function draw(widget: string | null): HTMLElement {
  const target = document.createElement('div');
  document.body.append(target);
  mounted.push(mount(WidgetIcon, { target, props: { name: 'users', widget, size: 15 } }));
  flushSync();
  return target;
}

afterEach(() => {
  for (const handle of mounted.splice(0)) void unmount(handle);
  document.body.innerHTML = '';
});

describe('the global mark', () => {
  test('a global sibling shows a globe badge over its own icon, by cell id or manifest id', () => {
    for (const id of ['task-manager-all', 'core.task-manager-all']) {
      const box = draw(id);
      expect(box.querySelector('[data-widget-globe]')).not.toBeNull();
      expect(box.querySelector('[data-widget-globe] svg')?.getAttribute('data-icon')).toBe('globe');
      expect(box.querySelectorAll('svg')[0]?.getAttribute('data-icon')).toBe('users');
    }
  });

  test('the local variant, and an icon with no widget, are drawn bare', () => {
    for (const id of ['huddle', 'core.task-manager', null]) {
      const box = draw(id);
      expect(box.querySelector('[data-widget-globe]')).toBeNull();
      expect(box.querySelectorAll('svg')).toHaveLength(1);
    }
  });

  test('the list answers false for nothing', () => {
    expect(isGlobalWidget(undefined)).toBe(false);
    expect(isGlobalWidget('')).toBe(false);
  });
});
