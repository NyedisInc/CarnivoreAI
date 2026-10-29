import { describe, expect, test } from 'vitest';
import type { OpView } from './migrate-store.svelte';
import { MAX_LISTED_FILES, movePanelState, notCopiedFiles, stepProgress } from './move-panel-state';

const base = { kind: 'project' as const, phase: 'pick' as const, machine: 'studio', busy: false, error: null, canApply: null, opState: null };

describe('the move panel state', () => {
  test('walks loading, refused, ready, moving, done and failed from the store fields alone', () => {
    expect(movePanelState({ ...base, machine: null })).toBe('pick');
    expect(movePanelState({ ...base, busy: true })).toBe('checking');
    expect(movePanelState({ ...base, error: 'a different project here is already named x' })).toBe('refused');
    expect(movePanelState({ ...base, phase: 'plan', canApply: true })).toBe('ready');
    expect(movePanelState({ ...base, phase: 'plan', canApply: false })).toBe('refused');
    expect(movePanelState({ ...base, phase: 'running', opState: 'applying' })).toBe('moving');
    expect(movePanelState({ ...base, phase: 'running', opState: 'flipped' })).toBe('done');
    expect(movePanelState({ ...base, phase: 'running', opState: 'failed' })).toBe('failed');
    expect(movePanelState({ ...base, kind: 'back', machine: null, busy: true })).toBe('checking');
  });

  test('counts the op step as n of total, and nothing before the op reports one', () => {
    const steps = ['prepare', 'code', 'rows', 'transcripts', 'verify', 'flip'];
    expect(stepProgress('verify', steps)).toEqual({ n: 5, total: 6 });
    expect(stepProgress(null, steps)).toBeNull();
    expect(stepProgress('unknown', steps)).toBeNull();
  });
});

const op = (detail: Record<string, unknown>, children: Partial<OpView['children'][number]>[] = []): OpView => ({
  id: 'o', state: 'flipped', step: null, error_code: null, detail, steps: [],
  children: children.map((c, i) => ({ id: `c${i}`, name: null, state: 'flipped', step: null, error_code: null, ...c })) });
const own = (names: unknown) => op({ summary: { task_files_not_copied: names } });

describe('the task files a move could not carry', () => {
  test('a company merges every child, in order', () => {
    const merged = notCopiedFiles(op({}, [{ task_files_not_copied: ['a.png'] }, { task_files_not_copied: ['b.pdf', 'c.txt'] }]));
    expect(merged).toEqual({ names: ['a.png', 'b.pdf', 'c.txt'], total: 3 });
  });
  test('same-named files all count: seven image.png stay seven', () => {
    expect(notCopiedFiles(own(Array(7).fill('image.png')))).toEqual({ names: Array(7).fill('image.png'), total: 7 });
    const across = notCopiedFiles(op({}, [{ task_files_not_copied: ['image.png'] }, { task_files_not_copied: ['image.png'] }]));
    expect(across.total).toBe(2);
  });
  test('an empty summary, no op, and malformed summaries list nothing', () => {
    const none = { names: [], total: 0 };
    expect(notCopiedFiles(null)).toEqual(none);
    expect(notCopiedFiles(own([]))).toEqual(none);
    expect(notCopiedFiles(op({}))).toEqual(none);
    expect(notCopiedFiles(op({ summary: null }))).toEqual(none);
    expect(notCopiedFiles(op({ summary: 'oops' }))).toEqual(none);
    expect(notCopiedFiles(own('abc'))).toEqual(none);
    expect(notCopiedFiles(own([1, null, {}]))).toEqual(none);
  });
  test('the list is capped and the rest counted, including what a child already capped', () => {
    const many = Array.from({ length: 25 }, (_, i) => `f${i}`);
    expect(notCopiedFiles(own(many))).toMatchObject({ total: 25, names: many.slice(0, MAX_LISTED_FILES) });
    const capped = notCopiedFiles(op({}, [{ task_files_not_copied: many.slice(0, 20), task_files_not_copied_more: 5 }, { task_files_not_copied: ['z'] }]));
    expect(capped.total).toBe(26);
    expect(capped.names).toHaveLength(20);
  });
});
