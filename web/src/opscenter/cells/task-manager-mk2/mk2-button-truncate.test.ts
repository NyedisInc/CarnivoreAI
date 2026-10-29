/** @vitest-environment jsdom */
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { afterEach, describe, expect, test } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

import Mk2MarkRead from './Mk2MarkRead.svelte';
import { markReadHolds, undoMarkRead } from './mk2-mark-read.svelte';
import { cssRules } from '../../../lib/base/css-rules';
import type { HuddleItem } from '../../../cplugs/huddle/huddle-model';

const apps: object[] = [];
afterEach(() => {
  while (apps.length) unmount(apps.pop()!, { outro: false });
  document.body.replaceChildren();
  for (const id of Object.keys(markReadHolds)) undoMarkRead(Number(id));
});

function measure(scroll: number, client: number): void {
  Object.defineProperty(HTMLElement.prototype, 'scrollWidth', { configurable: true, get: () => scroll });
  Object.defineProperty(HTMLElement.prototype, 'clientWidth', { configurable: true, get: () => client });
}

function rule(file: string, needle: string): Record<string, string> {
  const src = readFileSync(resolve(__dirname, file), 'utf8');
  const css = file.endsWith('.svelte') ? (/<style[^>]*>([\s\S]*)<\/style>/.exec(src)?.[1] ?? '') : src;
  return cssRules(css).find((r) => r.selector.endsWith(needle))?.decls ?? {};
}

describe('Mark II buttons stay inside their widget', () => {
  test('the tab strip lets its trailing slot shrink, so mark read is cut instead of widening the strip', () => {
    const trailing = rule('../../ui/tabs.css', '.oc-ptabs__trailing');
    expect(trailing.flex).toBe('0 1 auto');
    expect(trailing['min-width']).toBe('0');
    expect(trailing['max-width']).toBe('50%');
  });

  test('the schedule time and its edit key stay one unit but never grow wider than the row', () => {
    const when = rule('../../../cplugs/huddle/TaskManagerRow.svelte', '.tkm-when');
    expect(when.flex).toBe('none');
    expect(when['min-width']).toBe('0');
    expect(when['max-width']).toBe('100%');
  });

  test('a cut mark read shows an ellipsis span and the full label as its title; a fitting one has neither', async () => {
    const item = { id: 41, list: '7', text: 'x', state: 'open', thread: [], unread: true } as unknown as HuddleItem;
    const draw = (): HTMLButtonElement => {
      const target = document.createElement('div');
      document.body.appendChild(target);
      apps.push(mount(Mk2MarkRead, { target, props: { item } }));
      flushSync();
      return target.querySelector('[data-task-manager-mark-read]') as HTMLButtonElement;
    };
    measure(40, 80);
    const fits = draw();
    await Promise.resolve();
    expect(fits.querySelector('[data-btn-label]')).toBeNull();
    expect(fits.title).not.toBe('mark read');
    document.body.replaceChildren();

    measure(561, 120);
    const cut = draw();
    await Promise.resolve();
    expect(cut.querySelector(':scope > [data-btn-label]')?.textContent).toBe('mark read');
    expect(cut.title).toBe('mark read');
  });
});
