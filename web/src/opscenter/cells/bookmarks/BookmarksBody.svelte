<script lang="ts">
  import BookmarkRow from '../../../lib/bookmarks/BookmarkRow.svelte';
  import { Card, Checkbox, List } from '../../../lib/base';
    import type { BookmarkGroup } from './types';
  import { t } from '../../../lib/i18n/index.svelte';
  import { BookmarkWidgetActions } from './widget-actions.svelte';
  import { BookmarkPreviews, bookmarkPreviewSettings } from '../../../lib/bookmarks/preview-state.svelte';

  let { groups, live }: { groups: readonly BookmarkGroup[]; live: (rowId: number | null) => boolean } = $props();

  const actions = new BookmarkWidgetActions();
  const previews = new BookmarkPreviews();
  const previewOn = $derived(bookmarkPreviewSettings().show);
  const anyLive = $derived(groups.some((g) => g.marks.some((m) => live(m.session_row_id))));

  const shown = $derived(groups.filter((g) => g.marks.length > 0));

  function when(iso: string): string {
    const at = iso ? new Date(iso) : null;
    if (!at || Number.isNaN(at.getTime())) return '';
    return at.toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
  }
</script>

<div class="oc-bkm" data-bookmarks-body>
  {#snippet rowsOf(marks: BookmarkGroup['marks'])}
    <List>
      {#snippet children()}
        {#each marks as mark (mark.id)}
          <BookmarkRow title={mark.label || mark.snippet} by={mark.created_by} meta={when(mark.created_at)}
            busy={actions.busy !== null} canRewind={actions.armed && live(mark.session_row_id)}
            onBranch={() => void actions.branch(mark.session_row_id ?? 0, { bookmarkId: mark.id })}
            onRewind={() => void actions.rewind(mark.session_row_id ?? 0, { bookmarkId: mark.id })}
            onDelete={() => void actions.remove(mark)}
            onPreview={previewOn ? () => void previews.toggle(mark.id) : undefined}
            preview={previewOn && previews.isShown(mark.id) ? (previews.entry(mark.id) ?? null) : null} />
        {/each}
      {/snippet}
    </List>
  {/snippet}
  {#each shown as group (group.key)}
    {#if group.label !== null}
      <Card title={group.label} data-bookmarks-session={group.key}>
        {#snippet children()}{@render rowsOf(group.marks)}{/snippet}
      </Card>
    {:else}
      <section class="oc-bkm-group" data-bookmarks-session={group.key}>{@render rowsOf(group.marks)}</section>
    {/if}
  {/each}
  <Checkbox tone="danger" label={anyLive ? t('bookmarks.arm') : t('bookmarks.arm_not_live')} bind:checked={actions.armed} disabled={!anyLive || actions.busy !== null} data-arm />
  <p class="oc-bkm-notice" class:oc-bkm-notice--error={actions.notice?.error} role="status">{actions.notice?.text ?? ''}</p>
</div>

<style>
  @layer components {
    .oc-bkm { display: flex; flex-direction: column; gap: var(--oc-space-2); padding: var(--oc-space-1) var(--oc-space-1) var(--oc-space-2); font-family: var(--font-mono); }

    .oc-bkm-notice { min-height: 1lh; margin: 0 var(--oc-space-2); color: var(--oc-text-secondary); font-size: var(--oc-fs-body); }

    .oc-bkm-notice--error { color: var(--oc-coral); }
  }
</style>
