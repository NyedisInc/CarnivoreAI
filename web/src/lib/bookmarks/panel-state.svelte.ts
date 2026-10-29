import { ApiError } from '../../opscenter/api/auth.svelte';
import { t } from '../i18n/index.svelte';
import {
  addBookmark, branchFrom, deleteBookmark, listBookmarks, listTurns, rewindTo,
  type Bookmark, type Point, type Turn,
} from './api';

export interface Notice {
  text: string;
  error: boolean;
}

function messageOf(error: unknown): string {
  return error instanceof ApiError || error instanceof Error ? error.message : String(error);
}

export class BookmarksPanelState {
  readonly rowId: number;
  bookmarks = $state<Bookmark[]>([]);
  turnsOpen = $state(false);
  turns = $state<Turn[]>([]);
  totalTurns = $state(0);
  family = $state<string | null>(null);
  loading = $state(true);
  armed = $state(false);
  busy = $state<string | null>(null);
  notice = $state<Notice | null>(null);

  constructor(rowId: number) {
    this.rowId = rowId;
  }

  get moreTurns(): boolean {
    return this.turns.length < this.totalTurns;
  }

  async load(): Promise<void> {
    try {
      const listed = await listBookmarks(this.rowId);
      this.bookmarks = listed.bookmarks;
      this.family = listed.family;
      if (listed.family === 'claude' && listed.conversation) {
        const page = await listTurns(this.rowId, 0);
        this.turns = page.turns;
        this.totalTurns = page.total;
      }
    } catch (error) {
      this.notice = { text: messageOf(error), error: true };
    } finally {
      this.loading = false;
    }
  }

  async refreshBookmarks(): Promise<void> {
    try {
      const listed = await listBookmarks(this.rowId);
      this.bookmarks = listed.bookmarks;
    } catch (error) {
      this.notice = { text: messageOf(error), error: true };
    }
  }

  async loadMoreTurns(): Promise<void> {
    await this.run('more', async () => {
      const page = await listTurns(this.rowId, this.turns.length);
      this.turns = [...this.turns, ...page.turns];
      this.totalTurns = page.total;
      return null;
    });
  }

  async mark(entryUuid?: string, label = ''): Promise<boolean> {
    let saved = false;
    await this.run('mark', async () => {
      await addBookmark(this.rowId, entryUuid, label.trim());
      saved = true;
      await this.refreshBookmarks();
      return t('bookmarks.saved');
    });
    return saved;
  }

  async remove(id: number): Promise<void> {
    await this.run('remove', async () => {
      await deleteBookmark(id);
      this.bookmarks = this.bookmarks.filter((b) => b.id !== id);
      return null;
    });
  }

  async branch(point: Point): Promise<void> {
    await this.run('branch', async () => {
      const made = await branchFrom(this.rowId, point);
      return t('bookmarks.branched', { label: made.label });
    });
  }

  async rewind(point: Point): Promise<boolean> {
    if (!this.armed) return false;
    let done = false;
    await this.run('rewind', async () => {
      const result = await rewindTo(this.rowId, point, this.armed);
      done = result.ok || result.killed_live_pane;
      this.armed = false;
      await this.load();
      if (!result.ok) throw new Error(result.detail || t('bookmarks.rewind_failed'));
      return t(result.resumed_copy ? 'bookmarks.rewound' : 'bookmarks.rewound_other');
    });
    return done;
  }

  private async run(name: string, action: () => Promise<string | null>): Promise<void> {
    if (this.busy) return;
    this.busy = name;
    this.notice = null;
    try {
      const said = await action();
      if (said) this.notice = { text: said, error: false };
    } catch (error) {
      this.notice = { text: messageOf(error), error: true };
    } finally {
      this.busy = null;
    }
  }
}
