<script lang="ts">
  import Glyph from '../../../lib/Glyph.svelte';
  import { Card, Checkbox, IconButton } from '../../../lib/base';
  import BookmarkPreviewList from '../../../lib/bookmarks/BookmarkPreviewList.svelte';
  import { t } from '../../../lib/i18n/index.svelte';
  import KindGlyph from './KindGlyph.svelte';
  import { offersFor, type TimelineActions } from './actions.svelte';
  import { markTitle, kindWord, when } from './format';
  import type { Mark, SessionTimeline } from './types';

  interface Props {
    data: SessionTimeline;
    mark: Mark;
    rowId: number;
    live: boolean;
    actions: TimelineActions;
    menu: boolean;
    projectId: number | null;
    onClose?: () => void;
  }

  let { data, mark, rowId, live, actions, menu, projectId, onClose }: Props = $props();

  const offers = $derived(offersFor(mark, data));
  const peek = $derived(actions.peeks[mark.id] ?? null);
  const earlier = $derived(mark.conversation_id !== data.current_conversation);
  const busy = $derived(actions.busy !== null);
</script>

{#snippet closeKey()}
  {#if menu && onClose}
    <IconButton label={t('bookmarks.close')} variant="close" data-card-close onclick={onClose}><Glyph name="close" /></IconButton>
  {/if}
{/snippet}
{#snippet kindMark()}<KindGlyph kind={mark.kind} />{/snippet}
<Card title={kindWord(mark)} lead={kindMark} meta={`${when(mark.at)}${earlier ? ` · ${t('opscenter.cell.timeline.earlier')}` : ''}`} compact data-mark-card={mark.id} data-menu={menu || undefined} data-kind={mark.kind} actions={closeKey}>
  {#snippet children()}
    <p class="oc-tl-cardtitle">{markTitle(mark)}</p>
    {#if mark.snippet && mark.kind !== 'bookmark'}<p class="oc-tl-cardsnippet">{mark.snippet}</p>{/if}
    {#if peek}
      <BookmarkPreviewList entry={peek} />
    {:else if offers.peek && menu}
      <p class="oc-tl-cardnote" role="status">{t('opscenter.cell.timeline.peek.hint')}</p>
    {/if}
    {#if menu}
      <div class="oc-tl-menu" role="group" aria-label={t('opscenter.cell.timeline.menu')}>
        {#if offers.cut}
          <IconButton label={t('bookmarks.branch')} variant="quiet" data-branch disabled={busy} onclick={() => void actions.branch(rowId, mark)}><Glyph name="workflow" /></IconButton>
          <IconButton label={t('bookmarks.rewind')} variant="danger" data-rewind disabled={busy || !actions.armed || !live} onclick={() => void actions.rewind(rowId, mark)}><Glyph name="rewind" /></IconButton>
        {/if}
        {#if offers.bookmark}
          <IconButton label={t('bookmarks.mark')} variant="quiet" data-bookmark disabled={busy} onclick={() => void actions.bookmark(rowId, mark)}><Glyph name="bookmark-plus" /></IconButton>
        {/if}
        {#if offers.copy}
          <IconButton label={t('opscenter.cell.timeline.action.copy')} variant="quiet" data-open-copy disabled={busy} onclick={() => void actions.openCopy(mark)}><Glyph name="copy" /></IconButton>
        {/if}
        <IconButton label={t('opscenter.cell.timeline.action.open')} variant="quiet" data-open disabled={busy} onclick={() => void actions.open(data, mark.conversation_id, projectId)}><Glyph name="terminal" /></IconButton>
      </div>
      {#if offers.cut}
        <Checkbox tone="danger" label={live ? t('bookmarks.arm') : t('bookmarks.arm_not_live')} bind:checked={actions.armed} disabled={!live || busy} data-arm />
      {/if}
      <p class="oc-tl-notice" class:oc-tl-notice--error={actions.notice?.error} role="status">{actions.notice?.text ?? ''}</p>
    {/if}
  {/snippet}
</Card>

<style>
  @layer components {
    .oc-tl-cardnote { margin: 0; color: var(--oc-text-muted); font-size: var(--oc-fs-micro); }
    .oc-tl-cardtitle { margin: 0; color: var(--oc-text-primary); font-size: var(--oc-fs-body); overflow-wrap: anywhere; }
    .oc-tl-cardsnippet { margin: 0; color: var(--oc-text-secondary); font-size: var(--oc-fs-label); overflow-wrap: anywhere; }
    .oc-tl-menu { display: flex; flex-wrap: wrap; gap: var(--oc-space-1); }
    .oc-tl-notice { min-height: 1lh; margin: 0; color: var(--oc-text-secondary); font-size: var(--oc-fs-body); }
    .oc-tl-notice--error { color: var(--oc-coral); }
  }
</style>
