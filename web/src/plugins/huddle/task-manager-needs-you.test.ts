import { describe, expect, test } from 'vitest';
import { SECTION_ORDER, areaSubsections, sectionOf, statusSections } from './task-manager-status-sections';
import type { HuddleItem } from './huddle-model';

const mk = (id: number, status: string, needs_you = false, extra: Record<string, unknown> = {}): HuddleItem => ({
  id, list: 'all', text: `item ${id}`, note: '', position: id, created_by: 'joe', state: 'open', kind: '', number: null,
  revision: 1, created_seq: id, seq: id, deleted: false, thread: [], unread: false, group: null, status, section: status, needs_you, ...extra,
}) as unknown as HuddleItem;

describe('needs you section', () => {
  test('leads the order and holds the flagged items, which leave their status section', () => {
    expect(SECTION_ORDER[0]).toBe('needs_you');
    const items = [mk(1, 'open'), mk(2, 'question', true), mk(3, 'working', true), mk(4, 'review', true), mk(5, 'review')];
    const sections = statusSections(items);
    expect(sections.map((s) => s.key)).toEqual(['needs_you', 'review', 'open']);
    expect(sections[0]?.items.map((i) => i.id)).toEqual([2, 3]);
    expect(sections[1]?.items.map((i) => i.id)).toEqual([4, 5]);
    expect(sections.flatMap((s) => s.items).length).toBe(items.length);
    expect(sectionOf(items[2] as HuddleItem)).toBe('needs_you');
  });

  test('an item leaves it when answered, read or ticked (the flag drops) and returns to its status section', () => {
    const before = [mk(1, 'question', true), mk(2, 'working', true), mk(3, 'working', true)];
    expect(statusSections(before)[0]?.items.length).toBe(3);
    const after = [mk(1, 'open', false), mk(2, 'working', false), mk(3, 'done', false, { state: 'done', section: 'done' })];
    expect(statusSections(after).map((s) => s.key)).toEqual(['working', 'open', 'done']);
  });

  test('the area view and the project chips file a flagged item by its own status', () => {
    const items = [mk(1, 'question', true), mk(2, 'working', true)];
    expect(statusSections(items, false, false).map((s) => s.key)).toEqual(['question', 'working']);
    expect(areaSubsections(items, false, () => false).subs.map((s) => s.key)).toEqual(['question', 'working']);
  });

  test('hide completed never hides a flagged item, and an empty section is not drawn', () => {
    expect(statusSections([mk(1, 'open')], true).map((s) => s.key)).toEqual(['open']);
  });
});
