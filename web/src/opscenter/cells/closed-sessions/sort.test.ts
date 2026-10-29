import { describe, expect, test } from 'vitest';

import { SORT_KEYS, sortRows } from './sort.svelte';
import type { SessionRecord } from '../../api';

function row(opts: { id: string; title?: string; createdAt?: string }): SessionRecord {
  return {
    session_uuid: opts.id,
    origin: 'created',
    owned: true,
    lifecycle: 'stopped',
    title: opts.title ?? opts.id,
    working_dir: '~/dev/x',
    agent_type: null,
    agent_family: null,
    archived_at: null,
    created_at: opts.createdAt ?? '2026-09-25T00:00:00',
    last_work_at: null,
    project_id: null,
    tmux_name: null,
  };
}

describe('SORT_KEYS', () => {
  test('is exactly the two orderings this card can support, recent first as the default', () => {
    expect(SORT_KEYS).toEqual(['recent', 'name']);
  });
});

describe('sortRows', () => {
  const rows: SessionRecord[] = [
    row({ id: 'a', title: 'charlie', createdAt: '2026-09-25T09:00:00' }),
    row({ id: 'b', title: 'alpha', createdAt: '2026-09-25T11:00:00' }),
    row({ id: 'c', title: 'bravo', createdAt: '2026-09-25T10:00:00' }),
  ];

  test('recent: the server order is kept, never re-sorted by start time', () => {
    const ordered = sortRows(rows, 'recent');
    expect(ordered.map((r) => r.session_uuid)).toEqual(['a', 'b', 'c']);
  });

  test('name: alphabetical by the same label the NAME column prints', () => {
    const ordered = sortRows(rows, 'name');
    expect(ordered.map((r) => r.title)).toEqual(['alpha', 'bravo', 'charlie']);
  });

  test('never mutates the array it was handed', () => {
    const original = rows.slice();
    sortRows(rows, 'name');
    expect(rows).toEqual(original);
  });
});
