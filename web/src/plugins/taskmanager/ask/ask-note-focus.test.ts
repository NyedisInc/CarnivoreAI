/** @vitest-environment jsdom */
import { afterEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';
import AskQuestion from './AskQuestion.svelte';

let cmp: ReturnType<typeof mount> | null = null;
afterEach(() => { if (cmp) unmount(cmp); cmp = null; document.body.innerHTML = ''; vi.restoreAllMocks(); });

describe('add note', () => {
  test('focuses the new note input with preventScroll and scrolls it nearest', async () => {
    const focus = vi.spyOn(HTMLElement.prototype, 'focus');
    const into = vi.fn();
    HTMLElement.prototype.scrollIntoView = into;
    const target = document.body.appendChild(document.createElement('div'));
    cmp = mount(AskQuestion, { target, props: {
      question: { id: 'q', type: 'short_text', prompt: 'Why?', required: false }, number: 1, value: undefined, onChange: () => {}, onTake: () => {} } });
    flushSync();
    target.querySelector<HTMLButtonElement>('[data-ask-add-note="q"]')!.click();
    await tick(); await tick();
    const input = target.querySelector<HTMLInputElement>('[data-ask-note="q"]')!;
    expect(input).toBeTruthy();
    expect(document.activeElement).toBe(input);
    expect(focus.mock.calls.some((c) => (c[0] as FocusOptions | undefined)?.preventScroll === true)).toBe(true);
    expect(into).toHaveBeenCalledWith({ block: 'nearest' });
  });
});
