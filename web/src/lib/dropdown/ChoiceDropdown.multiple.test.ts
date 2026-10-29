/** @vitest-environment jsdom */
import { afterEach, describe, expect, it, vi } from 'vitest';
import { createRawSnippet, flushSync, mount, unmount } from 'svelte';
import ChoiceDropdown from './ChoiceDropdown.svelte';

const mounted: ReturnType<typeof mount>[] = [];
afterEach(() => {
  while (mounted.length) unmount(mounted.pop()!);
  document.body.innerHTML = '';
});

const row = createRawSnippet((item: () => { label: string }) => ({ render: () => `<span>${item().label}</span>` }));
const items = [{ id: 'a', label: 'alpha' }, { id: 'b', label: 'beta' }];

function open(props: Record<string, unknown>): HTMLElement {
  const target = document.body.appendChild(document.createElement('div'));
  mounted.push(mount(ChoiceDropdown, { target, props: { items, label: 'pick', row, ...props } }));
  return target;
}

describe('ChoiceDropdown multiple', () => {
  it('shows the summary when shut, marks every chosen row, and says the list is multiselectable', () => {
    const root = open({ multiple: true, values: ['a'], summary: 'alpha only', onToggle: vi.fn() });
    expect(root.querySelector('.cdd__summary')!.textContent).toBe('alpha only');
    root.querySelector<HTMLElement>('[data-choice-trigger]')!.click();
    flushSync();
    expect(root.querySelector('[data-choice-list]')!.getAttribute('aria-multiselectable')).toBe('true');
    expect(root.querySelector('[data-choice-option="a"]')!.getAttribute('aria-selected')).toBe('true');
    expect(root.querySelector('[data-choice-option="b"]')!.getAttribute('aria-selected')).toBe('false');
  });

  it('toggles a row and leaves the list open for the next pick', () => {
    const onToggle = vi.fn();
    const root = open({ multiple: true, values: ['a'], summary: 's', onToggle });
    root.querySelector<HTMLElement>('[data-choice-trigger]')!.click();
    flushSync();
    root.querySelector<HTMLElement>('[data-choice-option="b"]')!.click();
    flushSync();
    expect(onToggle).toHaveBeenCalledWith('b');
    expect(root.querySelector('[data-choice-list]')).not.toBeNull();
  });

  it('keeps the single-choice form as it was: a pick closes the list and calls onChange', () => {
    const onChange = vi.fn();
    const root = open({ value: 'a', onChange });
    expect(root.querySelector('.cdd__summary')).toBeNull();
    root.querySelector<HTMLElement>('[data-choice-trigger]')!.click();
    flushSync();
    expect(root.querySelector('[data-choice-list]')!.getAttribute('aria-multiselectable')).toBeNull();
    root.querySelector<HTMLElement>('[data-choice-option="b"]')!.click();
    flushSync();
    expect(onChange).toHaveBeenCalledWith('b');
    expect(root.querySelector('[data-choice-list]')).toBeNull();
  });
});

describe('ChoiceDropdown placeholder', () => {
  it('shows the placeholder line when no row is chosen, and none once one is', () => {
    expect(open({ value: '__none__', placeholder: 'pick it' }).querySelector('.cdd__summary')!.textContent).toBe('pick it');
    expect(open({ value: 'a', placeholder: 'pick it' }).querySelector('.cdd__summary')).toBeNull();
  });
});
