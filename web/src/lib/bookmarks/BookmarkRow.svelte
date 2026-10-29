
<script lang="ts">
  import Glyph from '../Glyph.svelte';
  import { IconButton, ListRow, Tag } from '../base';
  import { t } from '../i18n/index.svelte';
  import BookmarkPreviewList from './BookmarkPreviewList.svelte';
  import type { PreviewEntry } from './preview-state.svelte';

  interface Props {
    title: string;
    meta: string;
    by?: 'owner' | 'claude' | null;
    busy: boolean;
    canRewind: boolean;
    onBranch: () => void;
    onRewind: () => void;
    onMark?: () => void;
    onDelete?: () => void;
    onPreview?: () => void;
    preview?: PreviewEntry | null;
  }

  let { title, meta, by = null, busy, canRewind, onBranch, onRewind, onMark, onDelete, onPreview, preview = null }: Props = $props();
</script>

{#snippet metaLine()}{meta}{#if by === 'claude'} <Tag tone="info">{t('bookmarks.by_claude')}</Tag>{/if}{/snippet}
{#snippet keys()}
  {#if onPreview}
    <IconButton label={t('bookmarks.preview')} variant="quiet" pressed={preview !== null} data-bookmark-preview-toggle onclick={onPreview}><Glyph name="eye" /></IconButton>
  {/if}
  {#if onMark}
    <IconButton label={t('bookmarks.mark')} variant="quiet" disabled={busy} onclick={onMark}><Glyph name="bookmark-plus" /></IconButton>
  {/if}
  <IconButton label={t('bookmarks.branch')} variant="quiet" disabled={busy} data-branch onclick={onBranch}><Glyph name="workflow" /></IconButton>
  <IconButton label={t('bookmarks.rewind')} variant="danger" disabled={busy || !canRewind} data-rewind onclick={onRewind}><Glyph name="rewind" /></IconButton>
  {#if onDelete}
    <IconButton label={t('bookmarks.delete')} variant="danger" disabled={busy} data-delete onclick={onDelete}><Glyph name="trash" /></IconButton>
  {/if}
{/snippet}
{#snippet previewBlock()}{#if preview}<BookmarkPreviewList entry={preview} />{/if}{/snippet}

<ListRow wrap primary={title} secondary={metaLine} actions={keys}
  below={preview ? previewBlock : undefined} data-bookmark-row />
