/** @vitest-environment jsdom */
import { afterEach, describe, expect, it } from 'vitest';
import type { Component } from 'svelte';
import { boardHeaderKeys, registerBoardHeaderKey, resetBoardHeaderKeys, type BoardHeaderKeyProps } from './board-header-keys';

const Blank = (() => undefined) as unknown as Component<BoardHeaderKeyProps>;

afterEach(() => resetBoardHeaderKeys());

describe('board header keys', () => {
  it('lists nothing until a plugin registers', () => {
    expect(boardHeaderKeys()).toEqual([]);
  });

  it('lists enabled keys in registration order and leaves a disabled one out', () => {
    registerBoardHeaderKey({ id: 'a.one', component: Blank, enabled: () => true });
    registerBoardHeaderKey({ id: 'b.two', component: Blank, enabled: () => false });
    registerBoardHeaderKey({ id: 'c.three', component: Blank, enabled: () => true });
    expect(boardHeaderKeys().map((k) => k.id)).toEqual(['a.one', 'c.three']);
  });

  it('replaces a key registered again under the same id', () => {
    const first = (() => undefined) as unknown as Component<BoardHeaderKeyProps>;
    registerBoardHeaderKey({ id: 'a.one', component: first, enabled: () => true });
    registerBoardHeaderKey({ id: 'a.one', component: Blank, enabled: () => true });
    expect(boardHeaderKeys()).toHaveLength(1);
    expect(boardHeaderKeys()[0]!.component).toBe(Blank);
  });

  it('follows the switch the key reads', () => {
    let on = true;
    registerBoardHeaderKey({ id: 'a.one', component: Blank, enabled: () => on });
    expect(boardHeaderKeys()).toHaveLength(1);
    on = false;
    expect(boardHeaderKeys()).toEqual([]);
  });
});
