<!-- the detail pane -->
<script lang="ts">
  import { t } from '../../../i18n/index.svelte';
  import type { CardColumn, CardView } from '../../board-types';
  import type { BoardData, BoardLane } from '../../board-data.svelte';
  import LaneCard from '../swimlanes/LaneCard.svelte';
  import { laneTotal } from '../swimlanes/lane-model';
  import { dragging, dropIsNoop, isWaiting, moveCall, runCalls } from '../../card-actions.svelte';
  import { dropBefore, stack } from './column-model';

  interface Props {
    lane: BoardLane;
    data: BoardData;
    onOpen?: (card: CardView) => void;
    openId?: number | null;
  }
  let { lane, data, onOpen, openId = null }: Props = $props();

  let open = $state<Partial<Record<CardColumn, boolean>>>({});
  let over = $state(false);
  const groups = $derived(stack(lane, open));
  const drawn = $derived(groups.flatMap((g) => g.shown));

  function canDrop(card: CardView | null = dragging.card): card is CardView {
    return !!card && card.list_key === lane.list_key && isWaiting(card);
  }

  function dragOver(event: DragEvent): void {
    if (!canDrop()) return;
    event.preventDefault();
    if (event.dataTransfer) event.dataTransfer.dropEffect = 'move';
    over = true;
  }

  function dropIndex(event: DragEvent): number {
    const cards = [...(event.currentTarget as HTMLElement).querySelectorAll<HTMLElement>(':scope > [data-swarm-board-card]')];
    const at = cards.findIndex((el) => {
      const box = el.getBoundingClientRect();
      return event.clientY < box.top + box.height / 2;
    });
    return at < 0 ? cards.length : at;
  }

  async function drop(event: DragEvent): Promise<void> {
    event.preventDefault();
    over = false;
    const card = dragging.card;
    dragging.card = null;
    if (!canDrop(card)) return;
    const full = lane.columns[card.column] ?? [];
    const before = dropBefore(drawn, full, card, dropIndex(event));
    if (dropIsNoop(full, card.id, before)) return;
    await runCalls([moveCall(card.id, before)], t('swarm.board.act.ok.moved', { id: card.id }), data.refresh, (error) => t('swarm.board.act.error', { error }));
  }

  function flip(column: CardColumn): void {
    open = { ...open, [column]: !open[column] };
  }
</script>

<section class="sbjc" data-swarm-project-column={lane.list_key}>
  <div class="sbjc-head" title={lane.companyName ?? undefined}>
    <span class="sbjc-name">{lane.name}</span>
    <span class="sbjc-n">{laneTotal(lane.counts)}</span>
  </div>
  <div class="sbjc-stack" class:sbjc-stack--over={over} role="group" aria-label={lane.name}
       ondragover={dragOver} ondragleave={(e) => { if (!(e.currentTarget as HTMLElement).contains(e.relatedTarget as Node | null)) over = false; }}
       ondrop={(e) => void drop(e)}>
    {#each groups as group (group.column)}
      {#each group.shown as card (card.id)}<LaneCard {card} {data} {onOpen} selected={openId === card.id} glyph />{/each}
      {#if group.more > 0}
        <button type="button" class="sbjc-more" data-swarm-column-more={group.column} onclick={() => flip(group.column)}>{t('swarm.board.lane.more', { count: group.more, column: t(`swarm.board.col.${group.column}`) })}</button>
      {:else if open[group.column]}
        <button type="button" class="sbjc-more" data-swarm-column-fewer={group.column} onclick={() => flip(group.column)}>{t('swarm.board.lane.fewer')}</button>
      {/if}
    {/each}
  </div>
</section>

<style>
  @layer components {
    .sbjc {
      display: flex;
      flex: 1 1 0;
      flex-direction: column;
      min-width: 240px;
      font-family: var(--font-mono);
    }
    .sbjc-head {
      display: flex;
      align-items: center;
      gap: 8px;
      min-width: 0;
      padding: 0 2px 14px;
    }
    .sbjc-name {
      min-width: 0;
      overflow: hidden;
      color: var(--oc-text-bright);
      font-size: var(--oc-fs-label);
      font-weight: 600;
      letter-spacing: 0.14em;
      text-overflow: ellipsis;
      text-transform: uppercase;
      white-space: nowrap;
    }
    .sbjc-n {
      flex: none;
      color: var(--oc-text-muted);
      font-size: var(--oc-fs-body);
    }
    .sbjc-stack {
      display: flex;
      flex: 1;
      flex-direction: column;
      gap: 12px;
      min-height: 64px;
      border-radius: var(--oc-radius-sm);
    }
    .sbjc-stack--over {
      box-shadow: inset 0 0 0 1px var(--oc-line-panel);
    }
    .sbjc-more {
      width: 100%;
      height: 34px;
      border: 1px dashed var(--oc-line-rule);
      border-radius: var(--oc-radius-sm);
      background: transparent;
      color: var(--oc-text-secondary);
      font: inherit;
      font-family: var(--font-mono);
      font-size: var(--oc-fs-body);
      cursor: pointer;
    }
    .sbjc-more:hover {
      border-color: var(--oc-line-frame);
      color: var(--oc-text-bright);
    }
    @container swarm-columns (max-width: 720px) {
      .sbjc {
        flex: none;
        min-width: 0;
      }
    }
  }
</style>
