
<script lang="ts">
  import { t } from '../../../i18n/index.svelte';
  import StatusGlyph from '../../StatusGlyph.svelte';
  import TimelineNode from './TimelineNode.svelte';
  import { pct, type CardTrack, type TimelineGroup, type TimelineWindow } from './timeline-model';
  import { stamp } from './time-label';
  import type { BoardData } from '../../board-data.svelte';

  interface Props {
    group: TimelineGroup;
    win: TimelineWindow;
    nowSec: number;
    data: BoardData;
  }
  let { group, win, nowSec, data }: Props = $props();

  const nowPct = $derived(pct(nowSec, win));
  const workers = $derived(group.workers.map((id) => data.agent(id)).filter((a) => a !== undefined));
  /* no longer holds */
  const agentsOf = (ids: readonly number[]) => ids.map((id) => data.agent(id)).filter((a) => a !== undefined);
</script>

{#snippet label(k: CardTrack, child: boolean, last: boolean, chip: string)}
  <div class="sbt-label" data-swarm-tl-row={k.card.id} data-depth={child ? 1 : 0}>
    {#if child}
      <svg class="sbt-elbow" width="24" height="40" viewBox="0 0 24 40" aria-hidden="true"><path d={last ? 'M6 0 V20 H20' : 'M6 0 V20 H20 M6 20 V40'} /></svg>
    {/if}
    <StatusGlyph column={k.card.column} label={t(`swarm.board.col.${k.card.column}`)} />
    <span class="sbt-id">#{k.card.id}</span>
    <span class="sbt-title">{k.card.title}</span>
    {#if chip}<span class="sbt-chip">{chip}</span>{/if}
  </div>
{/snippet}

{#snippet track(k: CardTrack, thick: boolean, top: number, nodes: readonly number[])}
  <div class="sbt-track" class:sbt-track--thick={thick} style:top="{top}px" data-swarm-tl-bar={k.card.id}>
    {#each k.segments as s, i (i)}
      <div class="sbt-seg sbt-seg--{s.kind}" style:left="{pct(s.from, win)}%" style:width="{pct(s.to, win) - pct(s.from, win)}%"
        title={t(`swarm.board.timeline.seg.${s.kind}`, { from: stamp(s.from * 1000), to: stamp(s.to * 1000) })} data-swarm-tl-seg={s.kind}></div>
    {/each}
    {#if nodes.length}
      <span class="sbt-nodes" style:right="{100 - nowPct}%">
        {#each agentsOf(nodes) as agent (agent.id)}<TimelineNode {agent} {data} />{/each}
      </span>
    {/if}
  </div>
{/snippet}

<div data-swarm-tl-lane={group.lane.list_key}>
  {#if group.parents.length}
    <div class="sbt-head">
      <span class="sbt-lane">{group.lane.name}</span>
      <span class="sbt-note">{t('swarm.board.timeline.parents')}</span>
      <span class="sbt-head-end">
        {#if workers.length}
          <span class="sbt-working" data-swarm-tl-working>
            {#each workers as agent (agent.id)}<TimelineNode {agent} {data} />{/each}
            {t('swarm.board.timeline.working')}
          </span>
        {/if}
        <span class="sbt-note sbt-note--wide">{t('swarm.board.timeline.link_note')}</span>
      </span>
    </div>
    {#each group.parents as block (block.parent.card.id)}
      {@const kids = block.children}
      <div class="sbt-block" data-swarm-tl-parent={block.parent.card.id}>
        <div>
          {@render label(block.parent, false, false, t('swarm.board.timeline.children', { review: block.parent.card.children.in_review, total: block.parent.card.children.total }))}
          {#each kids as k, i (k.card.id)}{@render label(k, true, i === kids.length - 1, '')}{/each}
        </div>
        <div class="sbt-bars" style:height="{(kids.length + 1) * 40}px">
          {@render track(block.parent, true, 0, block.workers)}
          {#each kids as k, i (k.card.id)}{@render track(k, false, (i + 1) * 40, k.worker !== null ? [k.worker] : [])}{/each}
          {#each kids as k, i (k.card.id)}
            {#if k.reviewAt !== null && k.reviewAt * 1000 >= win.start}
              <div class="sbt-link" style:left="{pct(k.reviewAt, win)}%" style:height="{(i + 1) * 40}px" data-swarm-tl-link={k.card.id}></div>
              <div class="sbt-link-dot" style:left="{pct(k.reviewAt, win)}%" style:top="{(i + 1) * 40 + 20}px"></div>
            {/if}
          {/each}
        </div>
      </div>
    {/each}
  {/if}
  {#if group.loose.length}
    <div class="sbt-head" class:sbt-head--after={group.parents.length > 0}>
      <span class="sbt-lane">{group.lane.name}</span>
      <span class="sbt-note">{t('swarm.board.timeline.loose')}</span>
      {#if !group.parents.length && workers.length}
        <span class="sbt-head-end">
          <span class="sbt-working" data-swarm-tl-working>
            {#each workers as agent (agent.id)}<TimelineNode {agent} {data} />{/each}
            {t('swarm.board.timeline.working')}
          </span>
        </span>
      {/if}
    </div>
    {#each group.loose as k (k.card.id)}
      <div class="sbt-block">
        <div>{@render label(k, false, false, '')}</div>
        <div class="sbt-bars" style:height="40px">{@render track(k, false, 0, k.worker !== null ? [k.worker] : [])}</div>
      </div>
    {/each}
  {/if}
</div>

<style>
  @layer components {
    .sbt-head {
      display: flex;
      align-items: center;
      gap: 12px;
      min-height: 40px;
      margin-top: 10px;
      box-shadow: 0 1px 0 var(--oc-line-rule);
    }
    .sbt-head--after {
      margin-top: 18px;
    }
    .sbt-lane {
      flex: none;
      color: var(--oc-text-secondary);
      font-size: var(--oc-fs-label);
      letter-spacing: 0.14em;
      text-transform: uppercase;
    }
    .sbt-note {
      min-width: 0;
      overflow: hidden;
      color: var(--oc-text-muted);
      font-size: var(--oc-fs-body);
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .sbt-head-end {
      display: flex;
      flex: none;
      align-items: center;
      gap: 14px;
      margin-left: auto;
    }
    .sbt-working {
      display: inline-flex;
      align-items: center;
      gap: 4px;
      color: var(--oc-text-secondary);
      font-size: var(--oc-fs-body);
    }
    .sbt-working :global(.sbt-node-stem) {
      display: none;
    }
    .sbt-block {
      display: grid;
      grid-template-columns: var(--_label) minmax(0, 1fr);
      margin-top: 6px;
    }
    .sbt-label {
      display: flex;
      align-items: center;
      gap: 10px;
      height: 40px;
      min-width: 0;
      padding-right: 16px;
    }
    .sbt-elbow {
      flex: none;
      margin-left: 8px;
    }
    .sbt-elbow path {
      fill: none;
      stroke: var(--oc-line-frame);
      stroke-width: 1;
    }
    .sbt-id {
      flex: none;
      color: var(--oc-text-muted);
      font-size: var(--oc-fs-body);
    }
    .sbt-title {
      min-width: 0;
      overflow: hidden;
      color: var(--oc-text-bright);
      font-size: var(--oc-fs-body);
      font-weight: 600;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .sbt-chip {
      flex: none;
      padding: 1px 7px;
      border: 1px solid var(--oc-line-rule);
      border-radius: var(--oc-radius-sm);
      color: var(--oc-text-secondary);
      font-size: var(--oc-fs-label);
      white-space: nowrap;
    }
    .sbt-bars {
      position: relative;
    }
    .sbt-track {
      position: absolute;
      right: 0;
      left: 0;
      height: 40px;
    }
    .sbt-seg {
      position: absolute;
      top: 20px;
      height: 8px;
      min-width: 5px;
      margin-top: -4px;
      border-radius: 1px;
    }
    .sbt-track--thick .sbt-seg {
      height: 12px;
      margin-top: -6px;
    }
    .sbt-track .sbt-seg--wait {
      height: 0;
      min-width: 0;
      margin-top: 0;
      border-top: 1px dashed var(--oc-text-muted);
      border-radius: 0;
    }
    .sbt-seg--work { background: var(--oc-yellow); }
    .sbt-seg--unrecorded { background: var(--oc-text-dim); }
    .sbt-seg--review { background: var(--oc-cyan); }
    .sbt-nodes {
      position: absolute;
      top: -8px;
      display: flex;
      flex-direction: row-reverse;
      gap: 2px;
      margin-right: -9px;
    }
    .sbt-link {
      position: absolute;
      top: 20px;
      border-left: 1px dashed var(--oc-text-secondary);
    }
    .sbt-link-dot {
      position: absolute;
      width: 7px;
      height: 7px;
      margin: -3px 0 0 -3px;
      border-radius: 50%;
      background: var(--oc-text-secondary);
    }
    @container swarm-timeline (max-width: 720px) {
      .sbt-note--wide,
      .sbt-chip {
        display: none;
      }
      .sbt-label {
        gap: 6px;
        padding-right: 8px;
      }
      .sbt-elbow {
        width: 14px;
        margin-left: 0;
      }
    }
  }
</style>
