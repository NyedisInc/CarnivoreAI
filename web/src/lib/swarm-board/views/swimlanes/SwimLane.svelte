
<script lang="ts">
  import { t } from '../../../i18n/index.svelte';
  import { COLUMNS, type CardColumn, type CardView } from '../../board-types';
  import type { BoardData, BoardLane } from '../../board-data.svelte';
  import StatusGlyph from '../../StatusGlyph.svelte';
  import AgentFace from '../../AgentFace.svelte';
  import LaneCard from './LaneCard.svelte';
  import LaneChat from './LaneChat.svelte';
  import { MAX_FACES, cellCards, laneFaces, laneTotal, rollup } from './lane-model';
  import { beforeIdAt, columnCall, dragging, dropIsNoop, isWaiting, moveCall, runCalls } from '../../card-actions.svelte';

  interface Props {
    lane: BoardLane;
    data: BoardData;
    folded: boolean;
    onToggle: () => void;
    onOpen?: (card: CardView) => void;
    openId?: number | null;
    chat?: boolean;
  }
  let { lane, data, folded, onToggle, onOpen, openId = null, chat = false }: Props = $props();
  let over = $state<CardColumn | null>(null);

  let open = $state<Record<string, boolean>>({});
  const total = $derived(laneTotal(lane.counts));
  const faces = $derived(laneFaces(lane, (id) => data.agent(id)));
  const segments = $derived(rollup(lane.counts));
  const rollupLabel = $derived(t('swarm.board.lane.rollup', { todo: lane.counts.todo, in_progress: lane.counts.in_progress, review: lane.counts.review, done: lane.counts.done }));
  const bodyId = $derived(`swarm-lane-${lane.list_key.replace(/[^a-zA-Z0-9_-]/g, '-')}`);

  function canDrop(column: CardColumn, card: CardView | null = dragging.card): boolean {
    if (!card || card.list_key !== lane.list_key || card.lane_role) return false;
    return column !== card.column || isWaiting(card);
  }

  function dragOver(event: DragEvent, column: CardColumn): void {
    if (!canDrop(column)) return;
    event.preventDefault();
    if (event.dataTransfer) event.dataTransfer.dropEffect = 'move';
    over = column;
  }

  function dropIndex(event: DragEvent): number {
    const cell = event.currentTarget as HTMLElement;
    const cards = [...cell.querySelectorAll<HTMLElement>(':scope > [data-swarm-board-card]')];
    const at = cards.findIndex((el) => {
      const box = el.getBoundingClientRect();
      return event.clientY < box.top + box.height / 2;
    });
    return at < 0 ? cards.length : at;
  }

  async function drop(event: DragEvent, column: CardColumn): Promise<void> {
    event.preventDefault();
    over = null;
    const card = dragging.card;
    dragging.card = null;
    if (!card || !canDrop(column, card)) return;
    const cards = lane.columns[column] ?? [];
    const before = beforeIdAt(cards, card.id, dropIndex(event), card.list_key);
    const fail = (error: string) => t('swarm.board.act.error', { error });
    const id = card.id;
    if (column === card.column) {
      if (dropIsNoop(cards, id, before)) return;
      await runCalls([moveCall(id, before)], t('swarm.board.act.ok.moved', { id }), data.refresh, fail);
      return;
    }
    const calls = [columnCall(id, column)];
    if (before !== null && (column === 'todo' || column === 'in_progress')) calls.push(moveCall(id, before));
    const said = column === 'todo' && card.column === 'in_progress' ? t('swarm.board.act.ok.pause', { id })
      : column === 'done' ? t('swarm.board.act.ok.done', { id })
      : t('swarm.board.act.ok.reclassify', { id, column: t(`swarm.board.col.${column}`) });
    await runCalls(calls, said, data.refresh, fail);
  }

  function flip(column: CardColumn): void {
    open = { ...open, [column]: !open[column] };
  }
</script>

<section class="sbl" data-swarm-lane={lane.list_key} data-folded={folded ? 'true' : 'false'}>
  <button type="button" class="sbl-head" aria-expanded={!folded} aria-controls={bodyId} onclick={onToggle}>
    <svg class="sbl-caret" width="12" height="12" viewBox="0 0 12 12" aria-hidden="true">
      {#if folded}<path d="M4 2 L8 6 L4 10" />{:else}<path d="M2 4 L6 8 L10 4" />{/if}
    </svg>
    <span class="sbl-name">{lane.name}</span>
    {#if lane.companyName}<span class="sbl-pill" data-swarm-lane-company>{lane.companyName}</span>{/if}
    <span class="sbl-count">{total}</span>
    <span class="sbl-gap"></span>
    {#if folded}
      <span class="sbl-counts" data-swarm-lane-counts>
        {#each COLUMNS as column (column)}
          <span class="sbl-n"><StatusGlyph {column} size={12} label={t(`swarm.board.col.${column}`)} />{lane.counts[column]}</span>
        {/each}
      </span>
    {:else}
      <span class="sbl-done">{t('swarm.board.lane.done_of', { done: lane.counts.done, total })}</span>
    {/if}
    {#if faces.length}
      <span class="sbl-faces" data-swarm-lane-faces>
        {#each faces.slice(0, MAX_FACES) as face (face.agent.id)}<AgentFace agent={face.agent} working={face.working} colors={data.colors} looks={data.looks} />{/each}
        {#if faces.length > MAX_FACES}<span class="sbl-more-faces">{t('swarm.board.lane.more_faces', { count: faces.length - MAX_FACES })}</span>{/if}
      </span>
    {/if}
    <span class="sbl-rollup" role="img" aria-label={rollupLabel} data-swarm-lane-rollup>
      {#each segments as seg (seg.column)}
        <span class="sbl-seg-wrap" style:flex-grow={seg.count} data-swarm-rollup-seg={seg.column}>
          <span class="sbl-seg-icon"><StatusGlyph column={seg.column} size={10} plain /></span>
          <span class="sbl-seg sbl-seg--{seg.column}"></span>
        </span>
      {/each}
    </span>
  </button>
  {#if !folded}
    <div class="sbl-grid" class:sbl-grid--chat={chat} id={bodyId}>
      {#if chat}<LaneChat agent={lane.owner} />{/if}
      {#each COLUMNS as column (column)}
        {@const cell = cellCards(lane.columns[column] ?? [], lane.counts[column], !!open[column])}
        <div class="sbl-cell sbl-cell--{column}" class:sbl-cell--over={over === column} data-swarm-cell={column} role="group" aria-label={t(`swarm.board.col.${column}`)}
             ondragover={(e) => dragOver(e, column)} ondragleave={(e) => { if (!(e.currentTarget as HTMLElement).contains(e.relatedTarget as Node | null)) over = null; }}
             ondrop={(e) => void drop(e, column)}>
          <div class="sbl-cell-head"><StatusGlyph {column} size={12} /><span class="sbl-cell-name">{t(`swarm.board.col.${column}`)}</span><span class="sbl-cell-n">{lane.counts[column]}</span></div>
          {#each cell.shown as card (card.id)}<LaneCard {card} {data} {onOpen} selected={openId === card.id} />{/each}
          {#if cell.shown.length === 0}<span class="sbl-none">{t('swarm.board.lane.none')}</span>{/if}
          {#if cell.more > 0}
            <button type="button" class="sbl-more" data-swarm-cell-more onclick={() => flip(column)}>{t('swarm.board.lane.more', { count: cell.more, column: t(`swarm.board.col.${column}`) })}</button>
          {:else if open[column]}
            <button type="button" class="sbl-more" data-swarm-cell-fewer onclick={() => flip(column)}>{t('swarm.board.lane.fewer')}</button>
          {/if}
        </div>
      {/each}
    </div>
  {/if}
</section>

<style>
  @layer components {
    .sbl {
      margin-top: 20px;
    }
    .sbl-head {
      --_bd: var(--oc-line-rule);
      display: flex;
      align-items: center;
      gap: 12px;
      width: 100%;
      height: 44px;
      padding: 0 4px;
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
    .sbl-head:hover {
      background: var(--oc-ground-hover);
    }
    .sbl-caret {
      flex: none;
      fill: none;
      stroke: var(--oc-text-secondary);
      stroke-width: 1.5;
    }
    .sbl-name {
      min-width: 0;
      overflow: hidden;
      font-size: var(--oc-fs-body);
      font-weight: 600;
      letter-spacing: 0.14em;
      text-overflow: ellipsis;
      text-transform: uppercase;
      white-space: nowrap;
    }
    .sbl-pill {
      flex: none;
      padding: 1px 7px;
      border: 1px solid var(--oc-line-rule);
      border-radius: var(--oc-radius-sm);
      color: var(--oc-text-secondary);
      font-size: var(--oc-fs-label);
      letter-spacing: 0.06em;
      white-space: nowrap;
    }
    .sbl-count {
      flex: none;
      color: var(--oc-text-muted);
      font-size: var(--oc-fs-body);
    }
    .sbl-gap {
      flex: 1;
    }
    .sbl-done {
      flex: none;
      color: var(--oc-text-secondary);
      font-size: var(--oc-fs-body);
      white-space: nowrap;
    }
    .sbl-counts {
      display: inline-flex;
      flex: none;
      gap: 14px;
    }
    .sbl-n {
      display: inline-flex;
      align-items: center;
      gap: 5px;
      color: var(--oc-text-secondary);
      font-size: var(--oc-fs-body);
    }
    .sbl-faces {
      display: inline-flex;
      flex: none;
      align-items: center;
      gap: 4px;
    }
    .sbl-more-faces {
      color: var(--oc-text-muted);
      font-size: var(--oc-fs-label);
    }
    .sbl-rollup {
      display: flex;
      flex: none;
      align-items: flex-end;
      gap: 1px;
      width: 140px;
    }
    .sbl-seg-wrap {
      display: flex;
      flex: 1 1 0;
      flex-direction: column;
      align-items: center;
      gap: 3px;
      min-width: 2px;
      container-type: inline-size;
    }
    .sbl-seg-icon {
      display: inline-flex;
      height: 10px;
    }
    @container (max-width: 11px) {
      .sbl-seg-icon {
        visibility: hidden;
      }
    }
    .sbl-seg {
      width: 100%;
      height: 6px;
      border-radius: 1px;
      background: var(--oc-line-frame);
    }
    .sbl-seg--in_progress { background: var(--oc-yellow); }
    .sbl-seg--review { background: var(--oc-cyan); }
    .sbl-seg--done { background: var(--oc-green); }
    .sbl-grid {
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 12px;
      padding-top: 14px;
    }
    .sbl-grid--chat {
      grid-template-columns: minmax(0, 1.5fr) repeat(4, minmax(0, 1fr));
    }
    .sbl-cell {
      display: flex;
      flex-direction: column;
      gap: 10px;
      min-width: 0;
      min-height: 64px;
      padding: 10px;
      border-radius: var(--oc-radius-sm);
      background: color-mix(in srgb, var(--_tint) 7%, transparent);
    }
    .sbl-cell--todo { --_tint: var(--oc-text-muted); }
    .sbl-cell--in_progress { --_tint: var(--oc-yellow); }
    .sbl-cell--review { --_tint: var(--oc-cyan); }
    .sbl-cell--done { --_tint: var(--oc-green); }
    .sbl-cell--over {
      box-shadow: inset 0 0 0 1px var(--oc-line-panel);
    }
    .sbl-cell-head {
      display: none;
      align-items: center;
      gap: 8px;
      color: var(--oc-text-secondary);
      font-size: var(--oc-fs-label);
      letter-spacing: 0.14em;
      text-transform: uppercase;
    }
    .sbl-cell-n {
      color: var(--oc-text-muted);
      letter-spacing: 0;
    }
    @container swarm-board (max-width: 720px) {
      .sbl-head {
        flex-wrap: wrap;
        height: auto;
        min-height: 44px;
        padding: 8px 4px;
        row-gap: 8px;
      }
      .sbl-done {
        display: none;
      }
      .sbl-grid, .sbl-grid--chat {
        grid-template-columns: minmax(0, 1fr);
        gap: 16px;
      }
      .sbl-cell-head {
        display: flex;
      }
    }
    .sbl-none {
      padding: 6px 2px;
      color: var(--oc-text-muted);
      font-family: var(--font-mono);
      font-size: var(--oc-fs-body);
    }
    .sbl-more {
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
    .sbl-more:hover {
      border-color: var(--oc-line-frame);
      color: var(--oc-text-bright);
    }
  }
</style>
