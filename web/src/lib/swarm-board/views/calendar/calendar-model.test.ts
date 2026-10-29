import { describe, expect, it } from 'vitest';
import { bucketEvents, calendarDays, eventKind, facesByDay } from './calendar-model';
import type { CardEventRow } from './card-events.svelte';

const wed = new Date(2026, 9, 7, 15, 30).getTime();
const row = (item_id: number, hour: number, kind: string, from_col = '', to_col = '', day = 7): CardEventRow =>
  ({ item_id, list_key: '17', at: new Date(2026, 9, day, hour, 5).getTime() / 1000, kind, from_col, to_col, by: 'owner' });

describe('calendar model', () => {
  it('draws today, the last three days, or Monday to Sunday with later days ahead', () => {
    expect(calendarDays('day', wed).map((d) => d.date.getDate())).toEqual([7]);
    expect(calendarDays('three', wed).map((d) => d.date.getDate())).toEqual([5, 6, 7]);
    const week = calendarDays('week', wed);
    expect(week.map((d) => d.date.getDate())).toEqual([5, 6, 7, 8, 9, 10, 11]);
    expect(week.map((d) => d.today)).toEqual([false, false, true, false, false, false, false]);
    expect(week.filter((d) => d.ahead).length).toBe(4);
  });

  it('counts by the column move, never the kind alone', () => {
    expect(eventKind({ kind: 'moved', from_col: 'todo', to_col: 'review' })).toBe('review');
    expect(eventKind({ kind: 'finished', from_col: 'in_progress', to_col: 'review' })).toBe('review');
    expect(eventKind({ kind: 'dealt', from_col: 'todo', to_col: 'in_progress' })).toBe('started');
    expect(eventKind({ kind: 'started', from_col: '', to_col: '' })).toBeNull();
    expect(eventKind({ kind: 'done', from_col: 'review', to_col: 'done' })).toBe('approved');
    expect(eventKind({ kind: 'sent_back', from_col: 'review', to_col: 'in_progress' })).toBe('sent_back');
    expect(eventKind({ kind: 'handoff', from_col: '', to_col: '' })).toBeNull();
  });

  it('buckets distinct cards per kind per day and every counted event per hour', () => {
    const days = calendarDays('week', wed);
    const rows = [row(1, 9, 'created', '', 'todo'), row(2, 9, 'created', '', 'todo'), row(1, 10, 'moved', 'todo', 'review'),
      row(1, 11, 'moved', 'review', 'todo'), row(1, 12, 'moved', 'todo', 'review'), row(3, 8, 'created', '', 'todo', 6), row(4, 9, 'handoff')];
    const cells = bucketEvents(rows, days, (r) => r.list_key, () => true).get('17')!;
    expect(cells[2]!.counts).toEqual({ created: 2, started: 0, review: 1, approved: 0, sent_back: 0 });
    expect(cells[2]!.hours[9]).toBe(2);
    expect([cells[2]!.hours[10], cells[2]!.hours[12]]).toEqual([1, 1]);
    expect(cells[1]!.counts.created).toBe(1);
    expect(bucketEvents(rows, days, (r) => r.list_key, (r) => r.item_id === 2).get('17')![2]!.counts.created).toBe(1);
  });

  it('puts a working holder on the day its lease started', () => {
    const days = calendarDays('week', wed);
    const held = { holder: { agent_id: 9, name: null, since: 1, started_at: new Date(2026, 9, 6, 8).getTime() / 1000, beat_at: null } };
    const faces = facesByDay({ columns: { todo: [], in_progress: [held, held], review: [], done: [] } } as never, days);
    expect(faces[1]).toEqual([9]);
    expect(faces.flat().length).toBe(1);
  });
});
