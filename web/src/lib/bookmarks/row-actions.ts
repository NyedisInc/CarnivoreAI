import { sessions } from '../../opscenter/api';
import { raiseToast } from '../launchpad/recent-open-feedback';
import { t } from '../i18n/index.svelte';
import { openModal } from '../modal';
import BookmarksPanel from './BookmarksPanel.svelte';

export const BOOKMARK_TOAST_KIND = 'Bookmark';

function rowFor(tmuxName: string): { rowId: number; label: string } | null {
  const info = (sessions.data ?? []).find((s) => s.tmux_session === tmuxName);
  return typeof info?.session_row_id === 'number' ? { rowId: info.session_row_id, label: info.label ?? tmuxName } : null;
}

export function flashToast(ok: boolean, name: string, reason: string, now: number = Date.now()): Record<string, unknown> {
  return {
    id: `bookmark:${ok ? 'saved' : 'failed'}:${name}:${now}`,
    session_id: null,
    kind: BOOKMARK_TOAST_KIND,
    title: t(ok ? 'bookmarks.saved' : 'bookmarks.toast.failed'),
    body: ok ? name : reason,
    session_label: t('bookmarks.toast.surface'),
    local: true,
  };
}

export async function openSessionBookmarks(tmuxName: string): Promise<boolean> {
  const row = rowFor(tmuxName);
  if (!row) {
    raiseToast(flashToast(false, tmuxName, t('bookmarks.not_loaded')));
    return false;
  }
  await openModal(BookmarksPanel, { rowId: row.rowId, name: row.label });
  return true;
}
