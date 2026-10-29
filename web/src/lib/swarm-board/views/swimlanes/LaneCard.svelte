
<script lang="ts">
  import { t } from '../../../i18n/index.svelte';
  import { relative } from '../../../../opscenter/lib/format';
  import AgentFace from '../../AgentFace.svelte';
  import StatusGlyph from '../../StatusGlyph.svelte';
  import CardActions from '../../CardActions.svelte';
  import CardActionPanel from '../../CardActionPanel.svelte';
  import { collapsed, dragging } from '../../card-actions.svelte';
  import type { CardView } from '../../board-types';
  import type { BoardData, RosterAgent } from '../../board-data.svelte';

  interface Props {
    card: CardView;
    data: BoardData;
    onOpen?: (card: CardView) => void;
    selected?: boolean;
    glyph?: boolean;
  }
  let { card, data, onOpen, selected = false, glyph = false }: Props = $props();

  let mode = $state<'reclassify' | 'delete' | null>(null);
  const holder = $derived(card.holder ? (data.agent(card.holder.agent_id) ?? null) : null);
  const face = $derived<RosterAgent | null>(card.holder ? (holder ?? { id: card.holder.agent_id, display_name: card.holder.name ?? `#${card.holder.agent_id}`, rank: 'task', state: 'asleep', thread_key: '' }) : null);
  const age = $derived(relative((data.now / 1000 - card.updated_at) / 60));
  const queued = $derived(card.column === 'in_progress' && !card.holder && card.queued);
  const folded = $derived(collapsed.ids.includes(card.id));
  const movable = $derived(!card.lane_role && card.archived_at === null);
  const chip = $derived.by((): { key: string; tone: 'go' | 'warn' | 'bad' | 'quiet' | 'queued' } | null => {
    if (card.paused) return { key: 'swarm.board.chip.paused', tone: 'warn' };
    const mark = card.mark?.name;
    if (mark === 'stalled' || mark === 'validation_failed') return { key: `swarm.board.mark.${mark}`, tone: 'bad' };
    if (mark === 'validated') return { key: 'swarm.board.mark.validated', tone: 'go' };
    if (mark) return { key: `swarm.board.mark.${mark}`, tone: 'quiet' };
    if (card.column === 'in_progress' && card.holder) return { key: 'swarm.board.chip.working', tone: 'go' };
    if (queued) return { key: 'swarm.board.chip.queued', tone: 'queued' };
    return null;
  });
  const progress = $derived(card.column === 'in_progress' && typeof card.progress === 'number' ? Math.max(0, Math.min(100, Math.round(card.progress))) : null);
  const kids = $derived(glyph && card.children.total > 0 ? t('swarm.board.list.children', { done: card.children.done, total: card.children.total, review: card.children.in_review }) : '');
  const summary = $derived(card.summary && card.summary.trim() !== card.title.trim() ? card.summary : '');

  function dragStart(event: DragEvent): void {
    dragging.card = card;
    event.dataTransfer?.setData('text/plain', `#${card.id}`);
    if (event.dataTransfer) event.dataTransfer.effectAllowed = 'move';
  }
</script>


<!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_noninteractive_element_interactions -->
<article class="sbc" class:sbc--review={card.column === 'review'} class:sbc--queued={queued} class:sbc--line={folded} class:sbc--open={selected}
         data-swarm-board-card={card.id} data-column={card.column} data-queued={queued ? 'true' : 'false'} data-collapsed={folded ? 'true' : 'false'}
         draggable={movable && mode === null} ondragstart={dragStart} ondragend={() => (dragging.card = null)} onclick={() => onOpen?.(card)}>
  {#if folded}
    <div class="sbc-line">
      {#if glyph}<StatusGlyph column={card.column} label={t(`swarm.board.col.${card.column}`)} />{/if}
      <span class="sbc-id">#{card.id}</span>
      <button type="button" class="sbc-open sbc-line-title" onclick={(e) => { e.stopPropagation(); onOpen?.(card); }} data-swarm-card-open>{card.title}</button>
      {#if progress !== null}
        <span class="sbc-mini" role="img" aria-label={t('swarm.board.progress', { pct: progress })}><span class="sbc-bar" style:width="{progress}%"></span></span>
      {/if}
      {#if face}<AgentFace agent={face} working={card.column === 'in_progress'} colors={data.colors} looks={data.looks} />{/if}
      <CardActions {card} {data} bind:mode only={['collapse']} />
    </div>
  {:else}
    <div class="sbc-meta">
      {#if glyph}<StatusGlyph column={card.column} label={t(`swarm.board.col.${card.column}`)} />{/if}
      <span>#{card.id}</span>
      <span>{age}</span>
      <span class="sbc-gap"></span>
      {#if face}<AgentFace agent={face} working={card.column === 'in_progress'} colors={data.colors} looks={data.looks} />{/if}
    </div>
    <button type="button" class="sbc-open sbc-title" onclick={(e) => { e.stopPropagation(); onOpen?.(card); }} data-swarm-card-open>{card.title}</button>
    {#if summary}<p class="sbc-summary" data-swarm-card-summary>{summary}</p>{/if}
    {#if chip || card.auto_promote || card.archived_at !== null}
      <div class="sbc-chips">
        {#if chip}<span class="sbc-chip sbc-chip--{chip.tone}" data-swarm-board-chip={chip.tone}><span class="sbc-dot"></span>{t(chip.key)}</span>{/if}
        {#if card.auto_promote && card.column === 'todo'}<span class="sbc-chip sbc-chip--go" data-swarm-board-chip="auto_promote"><span class="sbc-dot"></span>{t('swarm.board.chip.auto_promote')}</span>{/if}
        {#if card.archived_at !== null}<span class="sbc-chip" data-swarm-board-chip="archived"><span class="sbc-dot"></span>{t('swarm.board.chip.archived')}</span>{/if}
      </div>
    {/if}
    {#if kids}<p class="sbc-kids" data-swarm-card-children>{kids}</p>{/if}
    <div class="sbc-foot">
      {#if progress !== null}
        <span class="sbc-progress" role="img" aria-label={t('swarm.board.progress', { pct: progress })}>
          <span class="sbc-track"><span class="sbc-bar" style:width="{progress}%"></span></span>
          <span class="sbc-pct">{progress}%</span>
        </span>
      {/if}
      <span class="sbc-gap"></span>
      <CardActions {card} {data} bind:mode />
    </div>
  {/if}
  {#if mode}
    {#key mode}<CardActionPanel {card} {data} bind:mode />{/key}
  {/if}
</article>

<style>
  @layer components {
    .sbc {
      min-width: 0;
      padding: 14px;
      border: 1px solid var(--oc-line-rule);
      border-radius: var(--oc-radius-sm);
      background: var(--oc-ground-card);
      font-family: var(--font-mono);
      cursor: pointer;
    }
    .sbc[draggable='true'] {
      cursor: grab;
    }
    .sbc:hover {
      border-color: var(--oc-line-panel);
    }
    .sbc--review {
      border-color: color-mix(in srgb, var(--oc-cyan) 45%, transparent);
    }
    .sbc--queued {
      border-style: dashed;
    }
    .sbc--open {
      border-color: var(--oc-text-muted);
    }
    .sbc--line {
      padding: 6px 8px 6px 12px;
    }
    .sbc-meta {
      display: flex;
      align-items: center;
      gap: 8px;
      min-height: 16px;
      color: var(--oc-text-muted);
      font-size: var(--oc-fs-body);
    }
    .sbc-gap {
      flex: 1;
    }
    .sbc-open {
      padding: 0;
      border: 1px solid transparent;
      background: transparent;
      font: inherit;
      font-family: var(--font-mono);
      text-align: left;
      cursor: pointer;
    }
    .sbc-title {
      display: -webkit-box;
      width: 100%;
      margin: 8px 0 0;
      overflow: hidden;
      color: var(--oc-text-bright);
      font-size: 14px;
      font-weight: 600;
      line-height: 1.45;
      word-break: break-word;
      -webkit-line-clamp: 2;
      line-clamp: 2;
      -webkit-box-orient: vertical;
    }
    .sbc-summary {
      display: -webkit-box;
      margin: 6px 0 0;
      overflow: hidden;
      color: var(--oc-text-secondary);
      font-size: var(--oc-fs-body);
      line-height: 1.5;
      word-break: break-word;
      -webkit-line-clamp: 2;
      line-clamp: 2;
      -webkit-box-orient: vertical;
    }
    .sbc-chips {
      display: flex;
      flex-wrap: wrap;
      gap: 8px 12px;
      margin-top: 10px;
    }
    .sbc-chip {
      --_c: var(--oc-text-secondary);
      display: inline-flex;
      align-items: center;
      gap: 5px;
      color: var(--_c);
      font-size: var(--oc-fs-label);
      letter-spacing: 0.06em;
      text-transform: uppercase;
    }
    .sbc-chip--go { --_c: var(--oc-green); }
    .sbc-chip--warn { --_c: var(--oc-yellow); }
    .sbc-chip--bad { --_c: var(--oc-coral); }
    .sbc-dot {
      width: 6px;
      height: 6px;
      border-radius: 50%;
      background: var(--_c);
    }
    .sbc-chip--queued .sbc-dot {
      box-sizing: border-box;
      border: 1px solid var(--_c);
      background: transparent;
    }
    .sbc-kids {
      margin: 10px 0 0;
      color: var(--oc-text-secondary);
      font-size: var(--oc-fs-label);
    }
    .sbc-foot {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: 8px;
      margin-top: 10px;
    }
    .sbc-progress {
      display: inline-flex;
      flex: 0 1 33%;
      align-items: center;
      gap: 8px;
      min-width: 60px;
    }
    .sbc-track {
      flex: 1;
      height: 3px;
      border-radius: 1px;
      background: var(--oc-line-frame);
    }
    .sbc-bar {
      display: block;
      height: 3px;
      border-radius: 1px;
      background: var(--oc-green);
    }
    .sbc-pct {
      color: var(--oc-text-secondary);
      font-size: var(--oc-fs-label);
    }
    .sbc-line {
      display: flex;
      align-items: center;
      gap: 8px;
      min-width: 0;
      color: var(--oc-text-muted);
      font-size: var(--oc-fs-body);
    }
    .sbc-id {
      flex: none;
    }
    .sbc-line-title {
      flex: 1;
      min-width: 0;
      overflow: hidden;
      color: var(--oc-text-bright);
      font-size: var(--oc-fs-body);
      font-weight: 600;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .sbc-mini {
      flex: none;
      width: 36px;
      height: 3px;
      border-radius: 1px;
      background: var(--oc-line-frame);
    }
  }
</style>
