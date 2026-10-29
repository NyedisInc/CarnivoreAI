import { describe, expect, it } from 'vitest';
import type { SessionBookmark } from '../../../lib/bookmarks/api';
import { isGlobalWidget } from '../../widgets/global-scope';
import { liveRowIds } from '../bookmarks/live-rows';
import { groupBySession } from './group';

function mark(id: number, uuid: string, label: string): SessionBookmark {
  return {
    id, session_uuid: uuid, session_row_id: id, claude_session_uuid: 'c', entry_uuid: 'e', label, created_by: 'owner',
    created_at: '', snippet: '', entry_timestamp: '', session_label: label ? `s-${uuid}` : '', session_tmux: '', family: 'claude',
  };
}

describe('bookmarks widgets', () => {
  it('groups newest first by session, sections ordered by their newest bookmark', () => {
    const groups = groupBySession([mark(5, 'b', 'x'), mark(4, 'a', 'x'), mark(3, 'b', 'x')], 'unnamed');
    expect(groups.map((g) => g.key)).toEqual(['b', 'a']);
    expect(groups[0]!.marks.map((m) => m.id)).toEqual([5, 3]);
    expect(groups[0]!.label).toBe('s-b');
  });

  it('names a session whose row is gone', () => {
    expect(groupBySession([mark(1, 'gone', '')], 'unnamed')[0]!.label).toBe('unnamed');
  });

  it('offers rewind only for rows live in the listing', () => {
    const live = liveRowIds([{ session_row_id: 1, activity_status: 'idle' }, { session_row_id: 2, activity_status: 'dead' }, { session_row_id: null }]);
    expect([...live]).toEqual([1]);
  });

  it('draws the globe on the all bookmarks widget only', () => {
    expect(isGlobalWidget('core.bookmarks-all')).toBe(true);
    expect(isGlobalWidget('core.bookmarks')).toBe(false);
  });
});
