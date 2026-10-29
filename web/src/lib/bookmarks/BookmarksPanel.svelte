
<script lang="ts">
  import { onMount } from 'svelte';
  import ModalShell from '../launchpad/ModalShell.svelte';
  import { t } from '../i18n/index.svelte';
  import { resourcePush } from '../resource-push/boot';
  import { sessions } from '../../opscenter/api';
  import Glyph from '../Glyph.svelte';
  import IconButton from '../base/IconButton.svelte';
  import { Button, Checkbox, Field, List } from '../base';
  import BookmarkRow from './BookmarkRow.svelte';
  import { BookmarksPanelState } from './panel-state.svelte';
  import { BookmarkPreviews, bookmarkPreviewSettings } from './preview-state.svelte';
  import { bookmarksTopic, type Point } from './api';

  interface Props {
    rowId: number;
    name: string;
    close: (value: null) => void;
  }

  let { rowId, name, close }: Props = $props();
  const FALLBACK_POLL_MS = 30000;
  // svelte-ignore state_referenced_locally
  const panel = new BookmarksPanelState(rowId);

  const live = $derived.by(() => {
    const row = (sessions.data ?? []).find((info) => info.session_row_id === rowId);
    return !!row && row.activity_status !== 'dead';
  });
  const canRewind = $derived(panel.armed && live);
  const previews = new BookmarkPreviews();
  const previewOn = $derived(bookmarkPreviewSettings().show);
  let name_ = $state('');

  async function add(): Promise<void> {
    if (await panel.mark(undefined, name_)) name_ = '';
  }

  onMount(() => {
    void panel.load();
    return resourcePush().pushOrPoll(() => void panel.refreshBookmarks(), FALLBACK_POLL_MS, [bookmarksTopic(rowId)]);
  });

  function when(iso: string): string {
    const at = iso ? new Date(iso) : null;
    if (!at || Number.isNaN(at.getTime())) return '';
    return at.toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
  }

  async function rewind(point: Point): Promise<void> {
    if (await panel.rewind(point)) close(null);
  }
</script>

<ModalShell title={t('bookmarks.title')} overlayClass="text-prompt-modal bm-modal" onCancel={() => close(null)}
  dismissable={panel.busy === null}>
  {#snippet head()}
    <div class="text-prompt-modal__head">
      <span class="text-prompt-modal__verb">&raquo; {t('bookmarks.title')}</span>
      <span class="bm-panel__session">{name}</span>
      <IconButton label={t('modal.close')} variant="close" icon="close" iconSize={14} data-modal-close
        onclick={() => close(null)} />
    </div>
  {/snippet}

  <div class="bm-panel" data-bookmarks-panel>
    {#if panel.family !== null && panel.family !== 'claude'}
      <p class="bm-panel__hint">{t('bookmarks.not_claude')}</p>
    {:else}
      <p class="bm-panel__hint">{t('bookmarks.hint')}</p>

      <form class="bm-panel__add" data-bookmark-add onsubmit={(event) => { event.preventDefault(); void add(); }}>
        <Field block bind:value={name_} maxlength={200} autocomplete="off"
          placeholder={t('bookmarks.name_placeholder')} aria-label={t('bookmarks.name_label')} data-bookmark-name />
        <IconButton type="submit" label={t('bookmarks.add')} variant="quiet" disabled={panel.busy !== null || panel.loading}
          data-bookmark-add-key><Glyph name="bookmark-plus" /></IconButton>
      </form>

      <div class="bm-panel__bar">
        <span class="bm-panel__label">{t('bookmarks.section.marked')}</span>
      </div>
      {#if panel.bookmarks.length}
        <List class="bm-panel__list">{#snippet children()}
          {#each panel.bookmarks as mark (mark.id)}
            <BookmarkRow title={mark.label || mark.snippet} by={mark.created_by}
              meta={when(mark.created_at)} busy={panel.busy !== null} {canRewind}
              onBranch={() => void panel.branch({ bookmarkId: mark.id })}
              onRewind={() => void rewind({ bookmarkId: mark.id })}
              onDelete={() => void panel.remove(mark.id)}
              onPreview={previewOn ? () => void previews.toggle(mark.id) : undefined}
              preview={previewOn && previews.isShown(mark.id) ? (previews.entry(mark.id) ?? null) : null} />
          {/each}
        {/snippet}</List>
      {:else}
        <p class="bm-panel__empty">{panel.loading ? t('bookmarks.loading') : t('bookmarks.empty')}</p>
      {/if}

      <div class="bm-panel__bar">
        <Button variant="quiet" size="sm" aria-expanded={panel.turnsOpen} data-turns-fold
          onclick={() => (panel.turnsOpen = !panel.turnsOpen)}>
          <span class="bm-panel__caret" aria-hidden="true">{panel.turnsOpen ? '\u25be' : '\u25b8'}</span>
          <span class="bm-panel__label">{t('bookmarks.section.turns')}</span>
        </Button>
      </div>
      {#if !panel.turnsOpen}
        
      {:else if panel.turns.length}
        <List class="bm-panel__list">{#snippet children()}
          {#each panel.turns as turn (turn.entry_uuid)}
            <BookmarkRow title={turn.snippet}
              meta={`${t('bookmarks.turn_number', { number: turn.number })} ${when(turn.timestamp)}`}
              busy={panel.busy !== null} {canRewind}
              onMark={() => void panel.mark(turn.entry_uuid)}
              onBranch={() => void panel.branch({ entryUuid: turn.entry_uuid })}
              onRewind={() => void rewind({ entryUuid: turn.entry_uuid })} />
          {/each}
        {/snippet}</List>
        {#if panel.moreTurns}
          <Button size="sm" data-bookmarks-more disabled={panel.busy !== null}
            onclick={() => void panel.loadMoreTurns()}>{t('bookmarks.turns.more')}</Button>
        {/if}
      {:else}
        <p class="bm-panel__empty">{panel.loading ? t('bookmarks.loading') : t('bookmarks.turns.empty')}</p>
      {/if}
    {/if}
    <p class="bm-panel__notice" class:bm-panel__notice--error={panel.notice?.error} role="status">{panel.notice?.text ?? ''}</p>
  </div>

  {#snippet footer()}
    <span class="bm-panel__arm">
      <Checkbox tone="danger" label={live ? t('bookmarks.arm') : t('bookmarks.arm_not_live')} bind:checked={panel.armed}
                disabled={!live || panel.busy !== null} data-arm />
    </span>
    <Button data-bookmarks-close onclick={() => close(null)}>{t('bookmarks.close')}</Button>
  {/snippet}
</ModalShell>

<style>
  @layer components {
    :global(.bm-modal .modal-content) {
      max-width: min(46rem, 94vw);
    }

    :global(.bm-modal .modal-footer) {
      flex-wrap: wrap;
      align-items: center;
      gap: var(--oc-space-2);
    }

    .bm-panel__session {
      flex: 1 1 auto;
      min-width: 0;
      overflow: hidden;
      color: var(--oc-text-primary);
      font-size: var(--oc-fs-status);
      white-space: nowrap;
      text-overflow: ellipsis;
    }

    .bm-panel {
      display: flex;
      flex-direction: column;
      gap: var(--oc-space-2);
      max-height: 70dvh;
      overflow-y: auto;
      font-family: var(--font-mono);
    }

    .bm-panel__hint,
    .bm-panel__empty {
      margin: 0;
      color: var(--oc-text-secondary);
      font-size: var(--oc-fs-body);
    }

    .bm-panel__empty {
      color: var(--oc-text-muted);
    }

    .bm-panel__caret {
      color: var(--oc-text-muted);
      font-size: var(--oc-fs-micro);
    }

    .bm-panel__bar {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: var(--oc-space-2);
      margin-top: var(--oc-space-1);
    }

    .bm-panel__label {
      color: var(--oc-text-muted);
      font-size: var(--oc-fs-micro);
      letter-spacing: var(--oc-tracking-label);
      text-transform: uppercase;
    }

    .bm-panel__list {
      border: var(--oc-border) solid var(--oc-line-panel);
      border-radius: var(--oc-radius-sm);
    }

    .bm-panel__add {
      display: flex;
      align-items: center;
      gap: var(--oc-space-2);
    }

    .bm-panel__add :global([data-field]) {
      flex: 1 1 auto;
      min-width: 0;
    }

    .bm-panel__add :global([data-bookmark-add-key]) {
      --oc-ibtn-size: 2rem;
      flex: none;
      color: var(--oc-green);
    }

    [data-bookmarks-more] {
      align-self: flex-start;
    }

    .bm-panel__notice {
      min-height: 1lh;
      margin: 0;
      color: var(--oc-text-secondary);
      font-size: var(--oc-fs-body);
    }

    .bm-panel__notice--error {
      color: var(--oc-coral);
    }

    .bm-panel__arm {
      display: flex;
      align-items: center;
      margin-right: auto;
      min-height: 2rem;
    }

    @media (pointer: coarse), (max-width: 600px) {
      .bm-panel__arm {
        flex: 1 0 100%;
        min-height: 2.75rem;
        margin-right: 0;
      }
    }
  }
</style>
