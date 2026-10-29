import { ApiError } from '../../opscenter/api/auth.svelte';
import { widgetSetting } from '../item-settings/store.svelte';
import { getPreview, type PreviewPart } from './api';

export interface PreviewEntry {
  status: 'loading' | 'ready' | 'error';
  parts: PreviewPart[];
  error: string;
  turns: number;
}

export function bookmarkPreviewSettings(): { show: boolean; turns: number } {
  const turns = widgetSetting('core.bookmarks', 'previewTurns');
  return {
    show: widgetSetting('core.bookmarks', 'showPreview') !== false,
    turns: typeof turns === 'number' && turns >= 1 ? Math.floor(turns) : 4,
  };
}

export class BookmarkPreviews {
  shown = $state<Record<string, boolean>>({});
  entries = $state<Record<string, PreviewEntry>>({});

  isShown(key: number | string): boolean {
    return this.shown[key] === true;
  }

  entry(key: number | string): PreviewEntry | undefined {
    return this.entries[key];
  }

  toggle(id: number): Promise<void> {
    return this.flip(id, (turns) => getPreview(id, turns));
  }

  private async flip(key: number | string, read: (turns: number) => Promise<{ parts: PreviewPart[] }>): Promise<void> {
    this.shown[key] = !this.isShown(key);
    const turns = bookmarkPreviewSettings().turns;
    const held = this.entries[key];
    if (!this.shown[key] || (held?.status === 'ready' && held.turns === turns)) return;
    this.entries[key] = { status: 'loading', parts: [], error: '', turns };
    try {
      this.entries[key] = { status: 'ready', parts: (await read(turns)).parts, error: '', turns };
    } catch (error) {
      const text = error instanceof ApiError || error instanceof Error ? error.message : String(error);
      this.entries[key] = { status: 'error', parts: [], error: text, turns };
    }
  }
}
