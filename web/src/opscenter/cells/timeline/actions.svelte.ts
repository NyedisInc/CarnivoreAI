import { ApiError } from '../../api/auth.svelte';
import { t } from '../../../lib/i18n/index.svelte';
import { addBookmark, type Point } from '../../../lib/bookmarks/api';
import { bookmarkPreviewSettings, type PreviewEntry } from '../../../lib/bookmarks/preview-state.svelte';
import { openConversation } from '../../../lib/conversation-open/open';
import { BookmarkWidgetActions, type Notice } from '../bookmarks/widget-actions.svelte';
import { getPeek, openRestorePoint } from './api';
import type { Mark, SessionTimeline } from './types';

export const CPLUG_DISABLED = 'cplug_disabled';

export function isPluginOff(error: unknown): boolean {
  if (!(error instanceof ApiError) || error.status !== 409) return false;
  if (error.code === CPLUG_DISABLED) return true;
  const payload = error.payload;
  const detail = payload && typeof payload === 'object' ? (payload as Record<string, unknown>)['detail'] : null;
  return !!detail && typeof detail === 'object' && (detail as Record<string, unknown>)['code'] === CPLUG_DISABLED;
}

function messageOf(error: unknown): string {
  return error instanceof ApiError || error instanceof Error ? error.message : String(error);
}

export interface Offers {
  cut: boolean;
  bookmark: boolean;
  copy: boolean;
  peek: boolean;
}

export function offersFor(mark: Mark, data: SessionTimeline): Offers {
  const here = mark.conversation_id === data.current_conversation;
  const claude = data.family === 'claude';
  const cuttable = claude && mark.entry_uuid !== null && mark.kind !== 'restore' && mark.kind !== 'restart';
  return {
    cut: cuttable && (mark.bookmark_id !== null || here),
    bookmark: cuttable && here && mark.bookmark_id === null,
    copy: mark.kind === 'restore' && mark.point_id !== null,
    peek: claude && mark.can_peek && mark.entry_uuid !== null,
  };
}

export function pointOf(mark: Mark): Point | null {
  if (mark.bookmark_id !== null) return { bookmarkId: mark.bookmark_id };
  return mark.entry_uuid !== null ? { entryUuid: mark.entry_uuid } : null;
}

export class TimelineActions {
  readonly bookmarks = new BookmarkWidgetActions();
  peeks = $state<Record<string, PreviewEntry>>({});
  private ownBusy = $state<string | null>(null);
  private ownNotice = $state<Notice | null>(null);

  get busy(): string | null {
    return this.ownBusy ?? this.bookmarks.busy;
  }

  get notice(): Notice | null {
    return this.ownNotice ?? this.bookmarks.notice;
  }

  get armed(): boolean {
    return this.bookmarks.armed;
  }

  set armed(value: boolean) {
    this.bookmarks.armed = value;
  }

  async branch(rowId: number, mark: Mark): Promise<void> {
    const point = pointOf(mark);
    if (!point) return;
    this.ownNotice = null;
    await this.bookmarks.branch(rowId, point);
  }

  async rewind(rowId: number, mark: Mark): Promise<void> {
    const point = pointOf(mark);
    if (!point) return;
    this.ownNotice = null;
    await this.bookmarks.rewind(rowId, point);
  }

  async bookmark(rowId: number, mark: Mark): Promise<void> {
    if (mark.entry_uuid === null) return;
    const entry = mark.entry_uuid;
    await this.run('bookmark', async () => {
      await addBookmark(rowId, entry);
      return t('bookmarks.saved');
    });
  }

  async openCopy(mark: Mark): Promise<void> {
    const point = mark.point_id;
    if (point === null) return;
    await this.run('copy', async () => {
      try {
        const result = await openRestorePoint(mark.conversation_id, point);
        return result.session.detail || t(`opscenter.cell.timeline.copy.${result.session.status}`);
      } catch (error) {
        if (isPluginOff(error)) throw new Error(t('opscenter.cell.timeline.copy.plugin_off'));
        throw error;
      }
    });
  }

  async open(data: SessionTimeline, conversationId: string, projectId: number | null): Promise<void> {
    await this.run('open', async () => {
      const outcome = await openConversation({ conversationId, sessionUuid: data.session_uuid, projectId });
      return t(`opscenter.cell.timeline.open.${outcome}`);
    });
  }

  async peek(rowId: number, mark: Mark): Promise<void> {
    if (mark.entry_uuid === null || this.peeks[mark.id] !== undefined) return;
    const turns = bookmarkPreviewSettings().turns;
    this.peeks[mark.id] = { status: 'loading', parts: [], error: '', turns };
    try {
      this.peeks[mark.id] = { status: 'ready', parts: (await getPeek(rowId, mark.conversation_id, mark.entry_uuid, turns)).parts, error: '', turns };
    } catch (error) {
      this.peeks[mark.id] = { status: 'error', parts: [], error: messageOf(error), turns };
    }
  }

  clearPeeks(): void {
    this.peeks = {};
  }

  private async run(name: string, action: () => Promise<string | null>): Promise<void> {
    if (this.busy) return;
    this.ownBusy = name;
    this.ownNotice = null;
    this.bookmarks.notice = null;
    try {
      const said = await action();
      if (said) this.ownNotice = { text: said, error: false };
    } catch (error) {
      this.ownNotice = { text: messageOf(error), error: true };
    } finally {
      this.ownBusy = null;
    }
  }
}
