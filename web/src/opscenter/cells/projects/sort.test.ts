import { describe, expect, test } from 'vitest';

import { SORT_KEYS, sortRows } from './sort.svelte';
import type { ProjectResponse } from '../../api';

function project(opts: { name: string; workAt?: string | null }): ProjectResponse {
  return {
    id: null,
    name: opts.name,
    path: `~/dev/${opts.name}`,
    description: null,
    root: null,
    work_at: opts.workAt ?? null,
    archived_at: null,
  };
}

describe('SORT_KEYS', () => {
  test('is exactly the two orderings this card can support, last_used first as the default', () => {
    expect(SORT_KEYS).toEqual(['last_used', 'name']);
  });
});

describe('sortRows', () => {
  const now = Date.parse('2026-09-25T12:00:00Z');
  const rows: ProjectResponse[] = [
    project({ name: 'charlie', workAt: '2026-09-25T09:00:00' }),
    project({ name: 'alpha', workAt: '2026-09-25T11:00:00' }),
    project({ name: 'bravo', workAt: null }),
  ];

  test('last_used: most recently worked on first, a project with no work_at sinks to the bottom', () => {
    const ordered = sortRows(rows, 'last_used', now);
    expect(ordered.map((r) => r.name)).toEqual(['alpha', 'charlie', 'bravo']);
  });

  test('name: alphabetical', () => {
    const ordered = sortRows(rows, 'name', now);
    expect(ordered.map((r) => r.name)).toEqual(['alpha', 'bravo', 'charlie']);
  });

  test('never mutates the array it was handed', () => {
    const original = rows.slice();
    sortRows(rows, 'name', now);
    expect(rows).toEqual(original);
  });
});
