import { describe, expect, test, vi } from 'vitest';
import { areaMenuNodes, barMenuNodes, type BarMenuInput } from './bar-menu';

function input(extra: Partial<BarMenuInput> = {}): BarMenuInput {
  return { size: 'cozy', pinned: false, editing: false, setSize: () => {}, togglePin: () => {}, toggleEdit: () => {}, onClose: () => {}, ...extra };
}

describe('barMenuNodes', () => {
  test('size radios (compact, cozy, detailed), pin bar, edit layout; hairlines between the three groups', () => {
    const menu = barMenuNodes(input());
    expect(menu.map((n) => n.id)).toEqual(['bar-size-compact', 'bar-size-cozy', 'bar-size-detailed', 'pin-bar', 'edit-layout']);
    expect(menu.filter((n) => n.sep).map((n) => n.id)).toEqual(['pin-bar', 'edit-layout']);
  });

  test('there is no hide-this-bar item, however the bar is set', () => {
    for (const extra of [{ pinned: true }, { editing: true }, { size: 'compact' as const }]) {
      const text = barMenuNodes(input(extra)).map((n) => `${n.id} ${n.label}`).join(' ');
      expect(text).not.toMatch(/hide|bar-show|show-bar/);
    }
  });

  test('the current size is the checked radio; a size picked writes it and closes the menu', () => {
    const setSize = vi.fn();
    const onClose = vi.fn();
    const menu = barMenuNodes(input({ size: 'detailed', setSize, onClose }));
    expect(menu.slice(0, 3).map((n) => n.checked)).toEqual([false, false, true]);
    menu[0]!.run!();
    expect(onClose).toHaveBeenCalled();
    expect(setSize).toHaveBeenCalledWith('compact');
  });

  test('the pin reads pin bar or unpin bar, writes through the toggle and closes the menu; there is no lock item', () => {
    const togglePin = vi.fn();
    const onClose = vi.fn();
    const pin = barMenuNodes(input({ togglePin, onClose })).find((n) => n.id === 'pin-bar')!;
    expect(pin.label).toBe('pin bar');
    pin.run!();
    expect(onClose).toHaveBeenCalled();
    expect(togglePin).toHaveBeenCalled();
    expect(barMenuNodes(input({ pinned: true })).find((n) => n.id === 'pin-bar')!.label).toBe('unpin bar');
    expect(barMenuNodes(input()).some((n) => /lock/.test(n.id))).toBe(false);
  });

  test('edit layout reads done editing while the editor is on, and is left out where the page cannot edit', () => {
    expect(barMenuNodes(input({ editing: true })).pop()!.id).toBe('done-editing');
    expect(barMenuNodes(input({ toggleEdit: null })).map((n) => n.id)).not.toContain('edit-layout');
  });
});

describe('areaMenuNodes', () => {
  test('closed, glance, full as radios keyed 1 2 3, then edit layout', () => {
    const setState = vi.fn();
    const menu = areaMenuNodes({ state: 'glance', editing: false, setState, toggleEdit: () => {}, onClose: () => {} });
    expect(menu.map((n) => [n.id, n.checked])).toEqual([['area-closed', false], ['area-glance', true], ['area-full', false], ['edit-layout', undefined]]);
    menu[2]!.run!();
    expect(setState).toHaveBeenCalledWith('full');
  });
});
