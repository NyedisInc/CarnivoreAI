import type { SessionBookmark } from '../../../lib/bookmarks/api';
import type { BookmarkGroup } from '../bookmarks/types';

export function groupBySession(marks: readonly SessionBookmark[], unnamed: string): BookmarkGroup[] {
  const groups = new Map<string, BookmarkGroup & { newest: string }>();
  for (const mark of marks) {
    let group = groups.get(mark.session_uuid);
    if (!group) {
      group = { key: mark.session_uuid, label: mark.session_label || mark.session_tmux || unnamed, marks: [], newest: mark.created_at };
      groups.set(mark.session_uuid, group);
    } else if (mark.created_at > group.newest) {
      group.newest = mark.created_at;
    }
    group.marks.push(mark);
  }
  return [...groups.values()].sort((a, b) => (a.newest < b.newest ? 1 : a.newest > b.newest ? -1 : 0))
    .map(({ newest: _newest, ...group }) => group);
}
