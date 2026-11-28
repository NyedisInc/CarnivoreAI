/** @vitest-environment jsdom */
import { afterEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';
import TaskManagerProjectHead from './TaskManagerProjectHead.svelte';
import { projectScrollTop } from './task-manager-sticky';

let handle: ReturnType<typeof mount> | null = null;
afterEach(() => {
  if (handle) unmount(handle);
  handle = null;
  document.body.innerHTML = '';
});

function setup(): { scroller: HTMLElement; scrollTo: ReturnType<typeof vi.fn>; toggle: ReturnType<typeof vi.fn>; head: HTMLElement } {
  const scroller = document.createElement('div');
  scroller.setAttribute('data-task-manager-scroll', '');
  const first = document.createElement('h2');
  first.setAttribute('data-task-manager-level', 'project');
  const block = document.createElement('div');
  block.getBoundingClientRect = () => ({ bottom: 500, top: 0 }) as DOMRect;
  scroller.append(first, block);
  document.body.append(scroller);
  const scrollTo = vi.fn();
  scroller.scrollTo = scrollTo as unknown as typeof scroller.scrollTo;
  scroller.getBoundingClientRect = () => ({ top: 0 }) as DOMRect;
  const toggle = vi.fn();
  handle = mount(TaskManagerProjectHead, { target: scroller, props: { list: '12', heading: 'alpha', count: 3, chips: [], folded: true, onToggle: toggle } });
  flushSync();
  const head = scroller.querySelectorAll<HTMLElement>('[data-task-manager-level="project"]')[1];
  Object.defineProperty(head, 'offsetHeight', { value: 30 });
  return { scroller, scrollTo, toggle, head };
}

describe('project bar scroll (item 385)', () => {
  test('the math: the dock is one bar per project above', () => {
    expect(projectScrollTop(600, 2, 30)).toBe(540);
    expect(projectScrollTop(10, 2, 30)).toBe(0);
  });

  test('clicking the rest of the bar scrolls under the dock and does not fold, even folded', () => {
    const { scroller, scrollTo, toggle } = setup();
    scroller.querySelector<HTMLElement>('[data-task-manager-project-scroll]')!.click();
    expect(scrollTo).toHaveBeenCalledWith({ top: 470, behavior: 'smooth' });
    expect(toggle).not.toHaveBeenCalled();
  });

  test('a click on the title folds it and does not scroll', () => {
    const { scroller, scrollTo, toggle } = setup();
    scroller.querySelector<HTMLElement>('[data-task-manager-project-title]')!.click();
    expect(toggle).toHaveBeenCalledTimes(1);
    expect(scrollTo).not.toHaveBeenCalled();
  });

  test('Enter and Space on the title fold; the chevron folds too; nothing scrolls', () => {
    const { scroller, scrollTo, toggle } = setup();
    const title = scroller.querySelector<HTMLElement>('[data-task-manager-project-title]')!;
    title.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
    title.dispatchEvent(new KeyboardEvent('keydown', { key: ' ', bubbles: true }));
    expect(toggle).toHaveBeenCalledTimes(2);
    scroller.querySelector<HTMLElement>('[data-task-manager-project-fold]')!.click();
    expect(toggle).toHaveBeenCalledTimes(3);
    expect(scrollTo).not.toHaveBeenCalled();
  });

  test('in the accordion the title opens a closed project and scrolls the open one, never calling a fold on the open one', () => {
    const scroller = document.createElement('div');
    document.body.append(scroller);
    const toggle = vi.fn();
    handle = mount(TaskManagerProjectHead, { target: scroller, props: { list: '12', heading: 'alpha', count: 3, chips: [], folded: true, accordion: true, onToggle: toggle } });
    flushSync();
    scroller.querySelector<HTMLElement>('[data-task-manager-project-title]')!.click();
    expect(toggle).toHaveBeenCalledTimes(1);
  });

  test('reduced motion scrolls instantly', () => {
    vi.stubGlobal('matchMedia', () => ({ matches: true }));
    const { scroller, scrollTo } = setup();
    scroller.querySelector<HTMLElement>('[data-task-manager-project-scroll]')!.click();
    expect(scrollTo).toHaveBeenCalledWith({ top: 470, behavior: 'auto' });
    vi.unstubAllGlobals();
  });
});
