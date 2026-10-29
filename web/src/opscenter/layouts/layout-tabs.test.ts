/** @vitest-environment jsdom */
import { describe, expect, it } from 'vitest';
import { addable, closeTab, layoutTabs, noteOpen, setTabs, visibleTabs, withTab, LAYOUT_TABS_KEY } from './layout-tabs.svelte';

describe('layout tabs', () => {
  it('adds a tab once and appends it', () => {
    expect(withTab(['a'], 'b')).toEqual(['a', 'b']);
    expect(withTab(['a', 'b'], 'a')).toEqual(['a', 'b']);
  });

  it('offers only layouts not yet tabbed', () => {
    const all = [{ layout_uuid: 'a' }, { layout_uuid: 'b' }, { layout_uuid: 'c' }];
    expect(addable(all, ['a', 'c']).map((l) => l.layout_uuid)).toEqual(['b']);
  });

  it('closing the active tab names its neighbour, closing another names none', () => {
    expect(closeTab(['a', 'b', 'c'], 'b', 'b')).toEqual({ tabs: ['a', 'c'], open: 'c' });
    expect(closeTab(['a', 'b', 'c'], 'c', 'c')).toEqual({ tabs: ['a', 'b'], open: 'b' });
    expect(closeTab(['a', 'b', 'c'], 'a', 'b')).toEqual({ tabs: ['b', 'c'], open: null });
  });

  it('never closes the last tab', () => {
    expect(closeTab(['a'], 'a', 'a')).toEqual({ tabs: ['a'], open: null });
  });

  it('drops deleted layouts from view but keeps the active one', () => {
    expect(visibleTabs(['a', 'gone'], ['a'], 'a')).toEqual(['a']);
    expect(visibleTabs(['a', 'gone'], ['a'], 'gone')).toEqual(['a', 'gone']);
    expect(visibleTabs(['a', 'x'], null, 'a')).toEqual(['a', 'x']);
  });

  it('tabs an opened layout and persists the list', () => {
    setTabs([]);
    noteOpen('a');
    noteOpen('b');
    noteOpen('a');
    expect(layoutTabs.uuids).toEqual(['a', 'b']);
    expect(JSON.parse(localStorage.getItem(LAYOUT_TABS_KEY) ?? '[]')).toEqual(['a', 'b']);
  });
});
