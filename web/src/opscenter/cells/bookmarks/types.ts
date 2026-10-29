import type { Bookmark } from '../../../lib/bookmarks/api';

export interface BookmarkGroup {
  key: string;
  label: string | null;
  marks: Bookmark[];
}
