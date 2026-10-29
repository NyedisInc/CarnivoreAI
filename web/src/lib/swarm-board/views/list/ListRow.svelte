
<script lang="ts">
  import { t } from '../../../i18n/index.svelte';
  import AgentFace from '../../AgentFace.svelte';
  import StatusGlyph from '../../StatusGlyph.svelte';
  import type { BoardData } from '../../board-data.svelte';
  import type { ListRow } from './list-model';

  interface Props {
    row: ListRow;
    data: BoardData;
    selected: boolean;
    onPick: () => void;
  }
  let { row, data, selected, onPick }: Props = $props();

  const card = $derived(row.card);
  const kids = $derived(card.children);
  const holder = $derived(card.holder ? (data.agent(card.holder.agent_id) ?? null) : null);
  const rollup = $derived(kids.total === 0 ? '' : kids.in_review > 0
    ? t('swarm.board.list.children', { done: kids.done, total: kids.total, review: kids.in_review })
    : t('swarm.board.lane.done_of', { done: kids.done, total: kids.total }));
</script>

<button type="button" class="sbr" class:sbr--on={selected} style:--_depth={row.depth} aria-pressed={selected}
        data-swarm-list-row={card.id} data-column={card.column} data-depth={row.depth} onclick={onPick}>
  {#if row.depth > 0}
    <svg class="sbr-branch" width="12" height="14" viewBox="0 0 12 14" aria-hidden="true"><path d="M2 0 V7 H11" /></svg>
  {/if}
  <StatusGlyph column={card.column} label={t(`swarm.board.col.${card.column}`)} />
  <span class="sbr-id">#{card.id}</span>
  <span class="sbr-title" class:sbr-title--parent={kids.total > 0}>{card.title}</span>
  <span class="sbr-end">
    {#if rollup}
      <span class="sbr-rollup">{rollup}</span>
    {:else if row.depth === 0}
      <span class="sbr-pill">{row.laneName}</span>
    {/if}
    {#if card.holder && !rollup}
      <AgentFace agent={holder ?? { id: card.holder.agent_id, display_name: card.holder.name ?? `#${card.holder.agent_id}`, rank: 'task', state: 'asleep', thread_key: '' }}
                 working={card.column === 'in_progress'} colors={data.colors} looks={data.looks} />
    {/if}
  </span>
</button>

<style>
  @layer components {
    .sbr {
      display: flex;
      align-items: center;
      gap: 12px;
      width: 100%;
      min-height: 42px;
      padding: 0 20px 0 calc(20px + var(--_depth) * 30px);
      border: 1px solid transparent;
      border-radius: 0;
      background: transparent;
      box-shadow: 0 1px 0 var(--oc-line-rule);
      color: var(--oc-text-bright);
      font: inherit;
      font-family: var(--font-mono);
      text-align: left;
      cursor: pointer;
    }
    .sbr:hover {
      background: var(--oc-ground-hover);
    }
    .sbr--on,
    .sbr--on:hover {
      background: var(--oc-ground-raised);
      box-shadow: inset 2px 0 0 var(--oc-cyan), 0 1px 0 var(--oc-line-rule);
    }
    .sbr-branch {
      flex: none;
      margin-left: -26px;
      margin-right: 2px;
      fill: none;
      stroke: var(--oc-text-muted);
      stroke-width: 1.2;
    }
    .sbr-id {
      flex: none;
      width: 38px;
      color: var(--oc-text-muted);
      font-size: var(--oc-fs-body);
    }
    .sbr-title {
      flex: 1;
      min-width: 0;
      overflow: hidden;
      font-size: 13px;
      font-weight: 500;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .sbr-title--parent {
      font-weight: 600;
    }
    .sbr-end {
      display: inline-flex;
      flex: none;
      align-items: center;
      gap: 8px;
      max-width: 45%;
    }
    .sbr-rollup {
      color: var(--oc-text-secondary);
      font-size: var(--oc-fs-body);
      white-space: nowrap;
    }
    .sbr-pill {
      min-width: 0;
      overflow: hidden;
      padding: 1px 7px;
      border: 1px solid var(--oc-line-rule);
      border-radius: var(--oc-radius-sm);
      color: var(--oc-text-secondary);
      font-size: var(--oc-fs-label);
      letter-spacing: 0.06em;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
  }
</style>
