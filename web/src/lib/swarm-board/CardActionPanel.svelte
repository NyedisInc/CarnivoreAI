
<script lang="ts">
  import { untrack } from 'svelte';
  import { t } from '../i18n/index.svelte';
  import { COLUMNS, type CardColumn, type CardView } from './board-types';
  import type { BoardData } from './board-data.svelte';
  import { columnCall, deleteCall, runCalls } from './card-actions.svelte';

  interface Props {
    card: CardView;
    data: BoardData;
    mode?: 'reclassify' | 'delete' | null;
  }
  let { card, data, mode = $bindable(null) }: Props = $props();

  let column = $state<CardColumn>(untrack(() => card.column));
  let note = $state('');
  let busy = $state(false);
  const fieldId = $derived(`swarm-card-${card.id}-reclassify`);

  async function send(): Promise<void> {
    const id = card.id;
    const fail = (error: string) => t('swarm.board.act.error', { error });
    busy = true;
    try {
      const ok = mode === 'delete'
        ? await runCalls([deleteCall(id)], t('swarm.board.act.ok.delete', { id }), data.refresh, fail)
        : await runCalls([columnCall(id, column, note.trim() || undefined)], t('swarm.board.act.ok.reclassify', { id, column: t(`swarm.board.col.${column}`) }), data.refresh, fail);
      if (ok) mode = null;
    } finally {
      busy = false;
    }
  }
</script>

<!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
<div class="sbp" data-swarm-card-panel={mode} onclick={(e) => e.stopPropagation()}>
  {#if mode === 'delete'}
    <p class="sbp-ask">{t('swarm.board.delete.confirm', { id: card.id })}</p>
  {:else}
    <label class="sbp-label" for={fieldId}>{t('swarm.board.reclassify.column')}</label>
    <select id={fieldId} class="sbp-field" bind:value={column} disabled={busy} data-swarm-reclassify-column>
      {#each COLUMNS as c (c)}<option value={c}>{t(`swarm.board.col.${c}`)}</option>{/each}
    </select>
    <label class="sbp-label" for="{fieldId}-note">{t('swarm.board.reclassify.note')}</label>
    <textarea id="{fieldId}-note" class="sbp-field" rows="2" maxlength="4000" placeholder={t('swarm.board.reclassify.placeholder')}
              bind:value={note} disabled={busy} data-swarm-reclassify-note></textarea>
  {/if}
  <div class="sbp-keys">
    <button type="button" class="oc-btn oc-btn--sm" disabled={busy} onclick={() => (mode = null)} data-swarm-panel-cancel>{t('swarm.board.panel.cancel')}</button>
    {#if mode === 'delete'}
      <button type="button" class="oc-btn oc-btn--sm oc-btn--danger" disabled={busy} onclick={() => void send()} data-swarm-delete-yes>{t('swarm.board.delete.yes')}</button>
    {:else}
      <button type="button" class="oc-btn oc-btn--sm oc-btn--confirm" disabled={busy || (column === card.column && !note.trim())} onclick={() => void send()}
              data-swarm-reclassify-apply>{t('swarm.board.reclassify.apply')}</button>
    {/if}
  </div>
</div>

<style>
  @layer components {
    /* box-shadow */
    .sbp {
      display: flex;
      flex-direction: column;
      gap: 6px;
      margin-top: 12px;
      padding-top: 12px;
      box-shadow: 0 -1px 0 var(--oc-line-rule);
      cursor: default;
    }
    .sbp-label {
      color: var(--oc-text-muted);
      font-size: var(--oc-fs-label);
      letter-spacing: 0.14em;
      text-transform: uppercase;
    }
    .sbp-field {
      box-sizing: border-box;
      width: 100%;
      padding: 6px 8px;
      border: 1px solid var(--oc-line-rule);
      border-radius: var(--oc-radius-sm);
      background: var(--oc-ground-field);
      color: var(--oc-text-primary);
      font-family: var(--font-mono);
      font-size: var(--oc-fs-body);
      resize: vertical;
    }
    .sbp-ask {
      margin: 0;
      color: var(--oc-text-primary);
      font-size: var(--oc-fs-body);
      line-height: 1.5;
    }
    .sbp-keys {
      display: flex;
      justify-content: flex-end;
      gap: 8px;
      margin-top: 4px;
    }
  }
</style>
