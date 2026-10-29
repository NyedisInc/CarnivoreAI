import { ApiError } from '../../api/auth.svelte';
import { t } from '../../../lib/i18n/index.svelte';
import { branchFrom, deleteBookmark, rewindTo, type Bookmark, type Point } from '../../../lib/bookmarks/api';

export interface Notice {
  text: string;
  error: boolean;
}

function messageOf(error: unknown): string {
  return error instanceof ApiError || error instanceof Error ? error.message : String(error);
}

export class BookmarkWidgetActions {
  armed = $state(false);
  busy = $state<string | null>(null);
  notice = $state<Notice | null>(null);
  confirmingDelete = $state<number | null>(null);

  async branch(rowId: number, point: Point): Promise<void> {
    await this.run('branch', async () => {
      const made = await branchFrom(rowId, point);
      return t('bookmarks.branched', { label: made.label });
    });
  }

  async rewind(rowId: number, point: Point): Promise<void> {
    if (!this.armed) return;
    await this.run('rewind', async () => {
      const result = await rewindTo(rowId, point, this.armed);
      this.armed = false;
      return t(result.resumed_copy ? 'bookmarks.rewound' : 'bookmarks.rewound_other');
    });
  }

  async remove(mark: Bookmark): Promise<void> {
    if (this.busy) return;
    if (this.confirmingDelete !== mark.id) {
      this.confirmingDelete = mark.id;
      this.notice = { text: t('bookmarks.delete_confirm'), error: false };
      return;
    }
    this.confirmingDelete = null;
    await this.run('remove', async () => {
      await deleteBookmark(mark.id);
      return null;
    });
  }

  private async run(name: string, action: () => Promise<string | null>): Promise<void> {
    if (this.busy) return;
    this.confirmingDelete = null;
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
