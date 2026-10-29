/** @vitest-environment jsdom */
import { existsSync, readdirSync, readFileSync, statSync } from 'node:fs';
import path from 'node:path';

import { afterEach, beforeEach, describe, expect, test } from 'vitest';
import { createRawSnippet, flushSync, mount, unmount } from 'svelte';

import CellFrame from '../shell/CellFrame.svelte';
import { META, metaFor } from '../engine/meta';
import { homeLayout } from '../engine/layout.svelte';
import type { SlotId } from '../engine/types';
import { inputFocus } from './input-focus.svelte';

const THE_STORE = 'opscenter/lib/input-focus.svelte.ts';

const SRC = ((): string => {
  for (const base of ['src', 'web/src', '../src', '../web/src']) {
    const candidate = path.resolve(process.cwd(), base);
    if (existsSync(path.join(candidate, 'opscenter/lib/input-focus.svelte.ts'))) return candidate;
  }
  throw new Error('web/src not found from ' + process.cwd());
})();

function sourceFiles(): string[] {
  const found: string[] = [];
  const walk = (dir: string): void => {
    for (const entry of readdirSync(dir)) {
      const full = path.join(dir, entry);
      if (statSync(full).isDirectory()) {
        walk(full);
        continue;
      }
      if (/\.(ts|svelte|js)$/.test(entry)) found.push(path.relative(SRC, full).split(path.sep).join('/'));
    }
  };
  walk(SRC);
  return found;
}

describe('the source tree holds one focus store and no second one', () => {
  test('only one module is named for the record', () => {
    const named = sourceFiles().filter((file) => /(^|\/)input-focus[^/]*$/.test(file));
    expect(named).toContain(THE_STORE);
    expect(named.length).toBeGreaterThan(0);
    const strays = named.filter((file) => !file.startsWith('opscenter/lib/input-focus'));
    expect(strays).toEqual([]);
  });

  test('every reader imports the same module, by a path that resolves to it', () => {
    const offenders: string[] = [];
    for (const file of sourceFiles()) {
      const text = readFileSync(path.join(SRC, file), 'utf8');
      for (const match of text.matchAll(/from\s+'([^']*input-focus[^']*)'/g)) {
        const spec = match[1];
        const resolved = path
          .relative(SRC, path.resolve(path.dirname(path.join(SRC, file)), `${spec}.ts`))
          .split(path.sep)
          .join('/');
        if (resolved !== THE_STORE) offenders.push(`${file} -> ${spec}`);
      }
    }
    expect(offenders).toEqual([]);
    const readers = sourceFiles().filter(
      (file) =>
        !file.startsWith('opscenter/lib/input-focus') &&
        /from\s+'[^']*input-focus[^']*'/.test(readFileSync(path.join(SRC, file), 'utf8')),
    );
    expect(readers.length).toBeGreaterThanOrEqual(3);
  });
});

const SLOT_A = 'terminal:ses_focus_a' as SlotId;
const SLOT_B = 'terminal:ses_focus_b' as SlotId;

function frame(slot: SlotId): { app: object; el: HTMLElement } {
  const target = document.createElement('div');
  document.body.appendChild(target);
  const app = mount(CellFrame, {
    target,
    props: {
      meta: metaFor(slot, META),
      instance: slot,
      widthState: '',
      heightState: '',
      store: homeLayout,
      body: createRawSnippet(() => ({ render: () => '<p>body</p>' })),
    },
  });
  flushSync();
  return { app, el: target.querySelector('.oc-frame') as HTMLElement };
}

beforeEach(() => {
  (globalThis as { ResizeObserver?: unknown }).ResizeObserver = class {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
  };
  homeLayout.add('terminal', 'ses_focus_a');
  homeLayout.add('terminal', 'ses_focus_b');
});

afterEach(() => {
  inputFocus.release(SLOT_A);
  inputFocus.release(SLOT_B);
  homeLayout.resetAll();
  document.body.innerHTML = '';
  localStorage.clear();
});

describe('one value moves the ring and the permission together', () => {
  test('the cell that glows is the cell whose keystrokes are permitted', () => {
    const a = frame(SLOT_A);
    const b = frame(SLOT_B);

    inputFocus.claim(SLOT_A);
    flushSync();
    expect(a.el.hasAttribute('data-oc-focus')).toBe(true);
    expect(a.el.getAttribute('aria-current')).toBe('true');
    expect(inputFocus.permits(SLOT_A)).toBe(true);
    expect(b.el.hasAttribute('data-oc-focus')).toBe(false);
    expect(b.el.getAttribute('aria-current')).toBe(null);
    expect(inputFocus.permits(SLOT_B)).toBe(false);

    inputFocus.claim(SLOT_B);
    flushSync();
    expect(a.el.hasAttribute('data-oc-focus')).toBe(false);
    expect(inputFocus.permits(SLOT_A)).toBe(false);
    expect(b.el.hasAttribute('data-oc-focus')).toBe(true);
    expect(b.el.getAttribute('aria-current')).toBe('true');
    expect(inputFocus.permits(SLOT_B)).toBe(true);

    unmount(a.app);
    unmount(b.app);
  });

  test('the line a screen reader gets is drawn from that same value', () => {
    const a = frame(SLOT_A);
    const b = frame(SLOT_B);
    inputFocus.claim(SLOT_A);
    flushSync();
    expect(a.el.querySelector('.oc-visually-hidden')?.textContent?.trim()).toBe(
      'this panel receives your typing',
    );
    expect(b.el.querySelector('.oc-visually-hidden')).toBe(null);
    unmount(a.app);
    unmount(b.app);
  });
});
