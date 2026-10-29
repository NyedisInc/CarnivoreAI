
<script lang="ts">
  import { t } from '../../i18n/index.svelte';
  import { readTab, writeTab } from '../../../opscenter/ui/tab-memory';
  import { COLUMNS, type CardCounts } from '../board-types';
  import BoardKey from './calendar/BoardKey.svelte';
  import { createEventWindow } from './calendar/card-events.svelte';
  import TimelineGroup from './timeline/TimelineGroup.svelte';
  import { SCALES, buildGroups, pct, timelineWindow, type TimelineScale } from './timeline/timeline-model';
  import { clock, day } from './timeline/time-label';
  import type { BoardViewProps } from '../view-props';

  let { data }: BoardViewProps = $props();

  const SCALE_KEY = 'swarm-board-timeline-scale';
  let scale = $state(readTab(SCALE_KEY, SCALES, 'day') as TimelineScale);

  const hour = $derived(Math.floor(data.now / 3600000) * 3600000);
  const win = $derived(timelineWindow(scale, hour));
  const range = $derived({ since: win.start / 1000, until: win.end / 1000 });
  const events = createEventWindow(data, () => range);
  const nowSec = $derived(data.now / 1000);

  const groups = $derived(buildGroups(data.lanes, events.rows, win, nowSec));
  const totals = $derived(Object.fromEntries(COLUMNS.map((c) => [c, data.lanes.reduce((n, lane) => n + lane.counts[c], 0)])) as CardCounts);
  const sentBack = $derived(groups.reduce((n, g) => n + [...g.parents.flatMap((p) => [p.parent, ...p.children]), ...g.loose].reduce((m, k) => m + k.sentBack, 0), 0));
  const tickLabel = (ms: number): string => (scale === 'day' ? clock(ms) : scale === 'three' ? `${day(ms)} ${clock(ms)}` : day(ms));
  const subtitle = $derived(scale === 'day' ? t('swarm.board.timeline.sub.day', { from: clock(win.start), to: clock(win.end) })
    : t(`swarm.board.timeline.sub.${scale}`, { from: day(win.start), to: day(win.end - 1) }));
  const nowPct = $derived(pct(nowSec, win));

  function pickScale(next: TimelineScale): void {
    scale = next;
    writeTab(SCALE_KEY, next);
  }
</script>

<div class="sbt" data-swarm-view="timeline" data-swarm-tl-scale={scale}>
  <div class="sbt-top">
    <span class="sbt-name">{t('swarm.board.timeline.title')}</span>
    <span class="sbt-sub" data-swarm-tl-sub>{subtitle}</span>
    <div class="sbt-scale" role="group" aria-label={t('swarm.board.timeline.scale')}>
      <span class="sbt-sub">{t('swarm.board.timeline.scale')}</span>
      {#each SCALES as s (s)}
        <button type="button" class="sbt-key" aria-pressed={scale === s} data-swarm-tl-scale-key={s} onclick={() => pickScale(s)}>{t(`swarm.board.timeline.scale.${s}`)}</button>
      {/each}
    </div>
  </div>
  <div class="sbt-axis">
    <div></div>
    <div class="sbt-ticks">
      {#each win.ticks as tick (tick)}
        <span class="sbt-tick" style:left="{pct(tick / 1000, win)}%">{tickLabel(tick)}</span>
      {/each}
    </div>
  </div>
  <div class="sbt-body" style:--_step="{100 / win.ticks.length}%">
    <div class="sbt-grid" aria-hidden="true">
      <div class="sbt-now" style:left="{nowPct}%"><span class="sbt-now-label">{t('swarm.board.timeline.now')}</span></div>
    </div>
    {#if events.status === 'error'}
      <p class="sbt-msg sbt-msg--bad" data-swarm-tl-error>{t('swarm.board.timeline.events_error', { error: events.error ?? '' })}</p>
    {:else if events.truncated}
      <p class="sbt-msg" data-swarm-tl-truncated>{t('swarm.board.timeline.truncated', { count: events.rows.length })}</p>
    {/if}
    {#if data.lanes.length === 0 && data.status === 'ok'}
      <p class="sbt-msg" data-swarm-board-empty>{data.search ? t('swarm.board.no_match', { q: data.search }) : t('swarm.board.empty')}</p>
    {:else if groups.length === 0 && data.status === 'ok' && events.status === 'ok'}
      <p class="sbt-msg" data-swarm-tl-quiet>{t('swarm.board.timeline.quiet')}</p>
    {/if}
    {#each groups as group (group.lane.list_key)}
      <TimelineGroup {group} {win} {nowSec} {data} />
    {/each}
  </div>
  <BoardKey {totals} {sentBack} />
</div>

<style>
  @layer components {
    .sbt {
      --_label: 430px;
      container: swarm-timeline / inline-size;
      min-width: 0;
      padding: 28px 0 var(--oc-space-5);
      font-family: var(--font-mono);
    }
    .sbt-top {
      display: flex;
      flex-wrap: wrap;
      align-items: baseline;
      gap: 12px 20px;
      margin-bottom: 18px;
    }
    .sbt-name {
      color: var(--oc-text-bright);
      font-size: var(--oc-fs-title);
      font-weight: 600;
    }
    .sbt-sub {
      color: var(--oc-text-muted);
      font-size: var(--oc-fs-label);
      letter-spacing: 0.14em;
      text-transform: uppercase;
    }
    .sbt-scale {
      display: flex;
      align-items: center;
      gap: 4px;
      margin-left: auto;
    }
    .sbt-scale .sbt-sub {
      margin-right: 4px;
    }
    .sbt-key {
      --_bd: var(--oc-line-rule);
      padding: 4px 11px;
      border: 1px solid var(--_bd);
      border-radius: var(--oc-radius-sm);
      background: transparent;
      color: var(--oc-text-secondary);
      font: inherit;
      font-size: var(--oc-fs-label);
      letter-spacing: 0.1em;
      text-transform: uppercase;
      white-space: nowrap;
      cursor: pointer;
    }
    .sbt-key:hover {
      color: var(--oc-text-bright);
    }
    .sbt-key[aria-pressed='true'] {
      --_bd: var(--oc-cyan);
      background: color-mix(in srgb, var(--oc-cyan) 12%, transparent);
      color: var(--oc-cyan);
    }
    .sbt-axis {
      display: grid;
      grid-template-columns: var(--_label) minmax(0, 1fr);
      box-shadow: 0 1px 0 var(--oc-line-rule);
    }
    .sbt-ticks {
      position: relative;
      height: 22px;
      overflow: hidden;
    }
    .sbt-tick {
      position: absolute;
      padding-left: 6px;
      color: var(--oc-text-muted);
      font-size: var(--oc-fs-label);
      letter-spacing: 0.1em;
      text-transform: uppercase;
      white-space: nowrap;
    }
    .sbt-body {
      position: relative;
    }
    .sbt-grid {
      position: absolute;
      top: 0;
      right: 0;
      bottom: 0;
      left: var(--_label);
      background: repeating-linear-gradient(90deg, transparent 0, transparent calc(var(--_step) - 1px), var(--oc-line-faint) calc(var(--_step) - 1px), var(--oc-line-faint) var(--_step));
      pointer-events: none;
    }
    .sbt-now {
      position: absolute;
      top: 0;
      bottom: 0;
      border-left: 1px solid var(--oc-text-primary);
    }
    .sbt-now-label {
      position: absolute;
      top: -20px;
      left: -18px;
      padding: 0 4px;
      background: var(--oc-ground-page);
      color: var(--oc-text-primary);
      font-size: var(--oc-fs-label);
      letter-spacing: 0.1em;
      text-transform: uppercase;
    }
    .sbt-msg {
      position: relative;
      margin: 14px 0 0;
      color: var(--oc-text-muted);
      font-size: var(--oc-fs-body);
    }
    .sbt-msg--bad {
      color: var(--oc-coral);
    }
    @container swarm-timeline (max-width: 720px) {
      .sbt-axis,
      .sbt-body {
        --_label: 132px;
      }
      .sbt-scale {
        margin-left: 0;
      }
      .sbt-tick:not(:nth-child(3n + 1)) {
        display: none;
      }
    }
  }
</style>
