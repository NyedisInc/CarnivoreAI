/** @vitest-environment jsdom */
import { afterEach, describe, expect, test } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { createRawSnippet, flushSync, mount, unmount } from 'svelte';
import TaskWrapper from './TaskWrapper.svelte';
import { isTaskState, legacyTaskState, nextTaskState, partsOf, TASK_STATES, type TaskState } from './task-wrapper';

let mounted: Record<string, unknown>[] = [];
afterEach(() => {
  for (const m of mounted) unmount(m);
  mounted = [];
  document.body.innerHTML = '';
});

const html = (markup: string) => createRawSnippet(() => ({ render: () => markup }));

function show(state: TaskState, onStateChange?: (next: TaskState) => void): HTMLElement {
  const target = document.createElement('div');
  document.body.append(target);
  mounted.push(mount(TaskWrapper, {
    target,
    props: {
      state, onStateChange, as: 'div', toggleProps: { 'data-task-toggle': 'x' },
      lead: html('<i data-slot="lead"></i>'), head: html('<b data-slot="head">title</b>'), keys: html('<u data-slot="keys"></u>'),
      tabs: html('<nav data-slot="tabs"></nav>'),
    },
  }) as Record<string, unknown>);
  flushSync();
  return target.firstElementChild as HTMLElement;
}

const slots = (root: HTMLElement): string[] => [...root.querySelectorAll('[data-slot]')].map((el) => (el as HTMLElement).dataset.slot as string);

describe('the state vocabulary', () => {
  test('three states, cycling compact, opened, detailed and back', () => {
    expect([...TASK_STATES]).toEqual(['compact', 'opened', 'detailed']);
    expect(TASK_STATES.map(nextTaskState)).toEqual(['opened', 'detailed', 'compact']);
    expect(['compact', 'opened', 'detailed'].every(isTaskState)).toBe(true);
    expect([isTaskState('normal'), isTaskState('expanded'), isTaskState(null), isTaskState(3)]).toEqual([false, false, false, false]);
  });

  test('a state saved under the round 4 names reads as its new name', () => {
    expect([legacyTaskState('normal'), legacyTaskState('expanded'), legacyTaskState('compact'), legacyTaskState('detailed')]).toEqual(['opened', 'detailed', 'compact', 'detailed']);
    expect([legacyTaskState('wide'), legacyTaskState(undefined)]).toEqual([null, null]);
  });

  test('only compact is one line: opened and detailed both draw the tab strip', () => {
    expect([...partsOf('compact')]).toEqual([]);
    expect([...partsOf('opened')]).toEqual(['tabs']);
    expect([...partsOf('detailed')]).toEqual(['tabs']);
  });
});

describe('TaskWrapper', () => {
  test('compact is the row alone: lead, head and keys', () => {
    const root = show('compact');
    expect(root.dataset.taskState).toBe('compact');
    expect(slots(root)).toEqual(['lead', 'head', 'keys']);
  });

  test('opened and detailed both draw the tabs, and nothing else under the row', () => {
    expect(slots(show('opened'))).toEqual(['lead', 'head', 'keys', 'tabs']);
    expect(slots(show('detailed'))).toEqual(['lead', 'head', 'keys', 'tabs']);
  });

  test('the row toggle reports aria-expanded for every state but compact and asks for the next state when pressed', () => {
    const asked: TaskState[] = [];
    for (const state of TASK_STATES) {
      const root = show(state, (next) => asked.push(next));
      const toggle = root.querySelector('button.oc-task__toggle') as HTMLButtonElement;
      expect(toggle.getAttribute('aria-expanded')).toBe(String(state !== 'compact'));
      expect(toggle.dataset.taskToggle).toBe('x');
      expect(toggle.querySelector('[data-slot="head"]')).not.toBeNull();
      toggle.click();
    }
    expect(asked).toEqual(['opened', 'detailed', 'compact']);
  });

  test('the lead and the keys are outside the toggle, so each stays its own control', () => {
    const root = show('opened');
    const toggle = root.querySelector('button.oc-task__toggle') as HTMLElement;
    expect(toggle.contains(root.querySelector('[data-slot="lead"]'))).toBe(false);
    expect(toggle.contains(root.querySelector('[data-slot="keys"]'))).toBe(false);
  });
});

describe('an empty part draws nothing (issue #1710 round 4)', () => {
  test('a tabs slot with no element inside is hidden, so it takes no gap and no height', () => {
    const target = document.createElement('div');
    document.body.append(target);
    mounted.push(mount(TaskWrapper, { target, props: { state: 'opened', head: html('<b>title</b>'), tabs: (() => {}) as never } }) as Record<string, unknown>);
    flushSync();
    expect((target.querySelector('[data-task-part="tabs"]') as HTMLElement).hidden).toBe(true);
  });
});

describe('the wrapper keeps its lead in one column and gives rows room (issue #1710 round 5, points 4 and 5)', () => {
  const css = readFileSync(resolve(process.cwd(), 'src/lib/base/task-wrapper.css'), 'utf8').replace(/\/\*[\s\S]*?\*\//g, '');

  test('the grip and check never shrink, so every row starts its status icon and title at the same x', () => {
    expect(css).toMatch(/\.oc-task__row > :not\(\.oc-task__toggle\)\s*\{\s*flex: none;/);
  });

  test('a row has more room than round 4: its padding and the gap between its parts are the space-2 token, no raw value', () => {
    const root = /\.oc-task \{[^}]*\}/.exec(css)![0];
    expect(root).toMatch(/gap: var\(--oc-space-2\)/);
    expect(root).toMatch(/padding-block: var\(--oc-space-2\)/);
    expect(css).not.toMatch(/\d+px/);
  });
});
