<script lang="ts">
  import { tick } from 'svelte';
  import type { SessionTimeline } from './types';
  import KindGlyph from './KindGlyph.svelte';
  import { BAND_X, HOOK_STEP, HOOK_X0, LABEL_PX, RAIL_COL_PX, RAIL_X, RULER_PX, type Column, type ColumnItem } from './column';
  import { COLUMN_INSET_PX, type Item, type Move } from './plot-model';
  import { tx } from './strings';
  import { clock, clusterShort, convShort, itemLabel, markShort } from './words';

  interface Props {
    column: Column;
    data: SessionTimeline;
    active: string | null;
    selected: string | null;
    onHover: (key: string | null) => void;
    onSelect: (key: string) => void;
    onMove: (move: Move) => string | null;
    onEscape: () => void;
  }

  let { column, data, active, selected, onHover, onSelect, onMove, onEscape }: Props = $props();

  const stop = $derived.by(() => {
    const keys = column.items.map((c) => c.item.key);
    return active && keys.includes(active) ? active : (column.items.find((c) => c.item.kind === 'conversation' && c.item.bar.current)?.item.key ?? keys[0] ?? null);
  });
  let bodyEl = $state<HTMLElement | null>(null);
  const KEYS: Readonly<Record<string, Move>> = { ArrowUp: 'up', ArrowDown: 'down', ArrowLeft: 'left', ArrowRight: 'right', Home: 'home', End: 'end' };

  async function keydown(event: KeyboardEvent): Promise<void> {
    if (event.key === 'Escape') { onEscape(); return; }
    const move = KEYS[event.key];
    if (!move) return;
    event.preventDefault();
    const key = onMove(move);
    await tick();
    if (key) bodyEl?.querySelector<HTMLElement>(`[data-key="${CSS.escape(key)}"]`)?.focus();
  }

  const pressed = (item: Item): boolean => selected === item.key || (item.kind === 'cluster' && item.marks.some((m) => `mark:${m.id}` === selected));
  const cursor = $derived(column.items.find((c) => c.item.kind !== 'conversation' && pressed(c.item))?.y ?? null);
  function leader(c: ColumnItem): string | null {
    if (c.labelTop === null) return null;
    const mid = c.labelTop + LABEL_PX / 2;
    return Math.abs(mid - c.y) < 1.5 ? null : `M ${RAIL_X + 6} ${c.y} H ${RAIL_X + 8} L ${RAIL_COL_PX + 2} ${mid}`;
  }
  const kindOf = (item: Item): 'compact' | 'bookmark' | 'restart' | 'restore' => (item.kind === 'mark' ? item.mark.kind : 'compact');
  const hookPath = (fromY: number, toY: number, track: number): string => {
    const x = HOOK_X0 - track * HOOK_STEP;
    return `M ${RAIL_X - 3} ${fromY} H ${x} V ${toY} H ${RAIL_X - 3}`;
  };
</script>

<div class="tlc" data-timeline-column style:--tlc-h={`${column.plotPx}px`} style:--tlc-ruler={`${RULER_PX}px`} style:--tlc-rail={`${RAIL_COL_PX}px`}
  style:--tlc-row={`${LABEL_PX}px`} style:--tlc-inset={`${COLUMN_INSET_PX}px`} style:--tlc-railx={`${RAIL_X}px`} style:--tlc-bandx={`${BAND_X}px`}>
  <div class="tlc-ruler" aria-hidden="true" data-timeline-axis>
    {#if column.ordered}
      <span class="tlc-ordered">{tx('plot.ordered')}</span>
    {:else}
      {#each column.ticks as t (t.key)}
        <span class="tlc-tick" data-kind={t.kind} data-anchor={t.anchor} style:top={`${t.x}px`}>{t.label}</span>
      {/each}
    {/if}
  </div>
  <!-- svelte-ignore a11y_interactive_supports_focus, a11y_no_noninteractive_element_interactions -->
  <div class="tlc-body" role="group" aria-label={tx('plot.label')} bind:this={bodyEl} onkeydown={(e) => void keydown(e)}
    onpointerleave={() => onHover(null)} data-timeline-rows>
    <svg class="tlc-lines" width={RAIL_COL_PX + 4} height={column.plotPx} aria-hidden="true" data-fit-backdrop>
      {#each column.ticks.filter((t) => t.kind !== 'break') as t (t.key)}
        <line class="tlc-grid" data-kind={t.kind} x1="0" x2={RAIL_X - 6} y1={t.x} y2={t.x} />
      {/each}
      {#if cursor !== null}<line class="tlc-cursor" x1="0" x2={RAIL_COL_PX + 4} y1={cursor} y2={cursor} />{/if}
      {#each column.hooks as h (h.key)}
        <path class="tlc-hook" data-hook={h.key} d={hookPath(h.fromX, h.toX, h.track)} />
        <line class="tlc-split" x1={RAIL_X - 5} x2={RAIL_X + 5} y1={h.fromX} y2={h.fromX} />
      {/each}
      {#each column.items as c (c.item.key)}
        {@const d = leader(c)}
        {#if d}<path class="tlc-leader" d={d} />{/if}
      {/each}
    </svg>
    {#each column.segs as s (s.bar.conversation_id)}
      
      <!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
      <div class="tlc-rail" data-fit-backdrop data-bar={s.bar.conversation_id} data-current={s.bar.current || undefined}
        data-selected={selected === `conv:${s.bar.conversation_id}` || undefined} style:top={`${s.x0}px`} style:height={`${s.x1 - s.x0}px`}
        onclick={() => onSelect(`conv:${s.bar.conversation_id}`)} onpointerenter={() => onHover(`conv:${s.bar.conversation_id}`)}></div>
    {/each}
    {#each column.bands as b (b.key)}
      <span class="tlc-band" data-state={b.state} aria-hidden="true" style:top={`${b.x0}px`} style:height={`${b.x1 - b.x0}px`}></span>
    {/each}
    {#each column.items as c (c.item.key)}
      {@const item = c.item}
      {#if item.kind === 'sleep'}
        <button type="button" class="tlc-sleep" data-key={item.key} data-open={item.gap.end === null || undefined} tabindex={stop === item.key ? 0 : -1}
          aria-pressed={pressed(item)} aria-label={itemLabel(item, data)} style:top={`${c.y}px`} style:height={`${item.x1 - c.y}px`}
          onclick={() => onSelect(item.key)} onfocus={() => onHover(item.key)} onpointerenter={() => onHover(item.key)}></button>
      {:else if item.kind === 'mark' || item.kind === 'cluster'}
        {#if c.labelTop === null}
          <button type="button" class="tlc-mark" data-key={item.key} data-kind={item.kind === 'mark' ? item.mark.kind : 'cluster'}
            tabindex={stop === item.key ? 0 : -1} aria-pressed={pressed(item)} aria-label={itemLabel(item, data)} style:top={`${c.y}px`}
            onclick={() => onSelect(item.key)} onfocus={() => onHover(item.key)} onpointerenter={() => onHover(item.key)}>
            {#if item.kind === 'cluster'}<span class="tlc-mark__n">{item.marks.length}</span>{:else}<KindGlyph kind={kindOf(item)} />{/if}
          </button>
        {:else}
          
          <!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
          <span class="tlc-mark" data-kind={item.kind === 'mark' ? item.mark.kind : 'cluster'} data-pressed={pressed(item) || undefined} aria-hidden="true"
            style:top={`${c.y}px`} onclick={() => onSelect(item.key)} onpointerenter={() => onHover(item.key)}>
            {#if item.kind === 'cluster'}<span class="tlc-mark__n">{item.marks.length}</span>{:else}<KindGlyph kind={kindOf(item)} />{/if}
          </span>
        {/if}
      {/if}
      {#if c.labelTop !== null && item.kind !== 'sleep'}
        <button type="button" class="tlc-label" data-key={item.key} data-kind={item.kind} data-current={(item.kind === 'conversation' && item.bar.current) || undefined}
          tabindex={stop === item.key ? 0 : -1} aria-pressed={pressed(item)} aria-label={itemLabel(item, data)} style:top={`${c.labelTop}px`}
          onclick={() => onSelect(item.key)} onfocus={() => onHover(item.key)} onpointerenter={() => onHover(item.key)}>
          {#if item.kind === 'conversation'}
            <span class="tlc-label__t" data-fit-truncate>{convShort(item.bar, item.index)}</span>
            <span class="tlc-label__w">{clock(item.bar.started_at)}</span>
          {:else if item.kind === 'mark'}
            <span class="tlc-label__t" data-fit-truncate>{markShort(item.mark)}</span>
            <span class="tlc-label__w">{clock(item.mark.at)}</span>
          {:else if item.kind === 'cluster'}
            <span class="tlc-label__t" data-fit-truncate>{clusterShort(item.marks)}</span>
            <span class="tlc-label__w">{clock(item.marks[0]!.at)}</span>
          {/if}
        </button>
      {/if}
    {/each}
  </div>
</div>

<style>
  @layer components {
    .tlc {
      position: relative;
      display: grid;
      grid-template-columns: var(--tlc-ruler) minmax(0, 1fr);
      box-sizing: content-box;
      height: var(--tlc-h);
      padding: var(--tlc-inset) 0;
      min-width: 0;
      font-family: var(--font-mono);
    }

    .tlc-ruler {
      position: relative;
      box-shadow: inset calc(var(--oc-border) * -1) 0 0 var(--oc-line-faint);
      color: var(--oc-text-muted);
      font-size: var(--oc-fs-micro);
      letter-spacing: var(--oc-tracking-label);
    }

    .tlc-tick {
      position: absolute;
      right: 0.375rem;
      line-height: 0.75rem;
      text-align: right;
      white-space: pre-line;
      transform: translateY(-50%);
    }

    .tlc-tick[data-anchor='start'] { transform: none; }
    .tlc-tick[data-anchor='end'] { transform: translateY(-100%); }
    .tlc-tick[data-kind='day'],
    .tlc-tick[data-kind='start'] { color: var(--oc-text-secondary); }
    .tlc-tick[data-kind='break'] { color: var(--oc-text-dim); }
    .tlc-ordered { position: absolute; top: 0; right: 0.375rem; color: var(--oc-text-dim); writing-mode: vertical-rl; }

    .tlc-body {
      position: relative;
      min-width: 0;
    }

    .tlc-lines {
      position: absolute;
      top: 0;
      left: 0;
      overflow: visible;
      pointer-events: none;
    }

    .tlc-grid { stroke: var(--oc-line-faint); stroke-width: 1; }
    .tlc-grid[data-kind='day'] { stroke: var(--oc-text-dim); stroke-dasharray: 2 2; }
    .tlc-cursor { stroke: var(--oc-text-muted); stroke-width: 1; stroke-dasharray: 3 2; }
    .tlc-hook { fill: none; stroke: var(--oc-cyan); stroke-width: 1; opacity: 0.85; }
    .tlc-split { stroke: var(--oc-cyan); stroke-width: 1; }
    .tlc-leader { fill: none; stroke: var(--oc-line-rule); stroke-width: 1; }

    .tlc-rail {
      position: absolute;
      left: calc(var(--tlc-railx) - 0.1875rem);
      width: 0.375rem;
      box-sizing: border-box;
      border: var(--oc-border) solid var(--oc-line-panel);
      border-radius: var(--oc-radius-sm);
      background: var(--oc-ground-field);
      cursor: pointer;
    }

    .tlc-rail[data-current] { border-color: var(--oc-cyan); }
    .tlc-rail[data-selected] { border-color: var(--oc-text-primary); }

    /* waiting on you */
    .tlc-band {
      position: absolute;
      left: var(--tlc-bandx);
      width: 0.125rem;
      background: color-mix(in oklab, var(--oc-text-dim) 45%, transparent);
      pointer-events: none;
    }

    .tlc-band[data-state='busy'] { background: var(--oc-green); }
    .tlc-band[data-state='waiting'] { z-index: 1; background: var(--oc-yellow); }

    .tlc-sleep {
      position: absolute;
      left: calc(var(--tlc-railx) - 0.3125rem);
      width: 0.625rem;
      padding: 0;
      border: var(--oc-border) solid transparent;
      background: repeating-linear-gradient(45deg, transparent 0 0.1875rem, var(--oc-text-dim) 0.1875rem 0.25rem);
      opacity: 0.7;
      cursor: pointer;
    }

    .tlc-sleep[data-open] { box-shadow: inset 0 calc(var(--oc-border) * -1) 0 var(--oc-text-dim); }
    .tlc-sleep:hover,
    .tlc-sleep[aria-pressed='true'] { border-color: var(--oc-text-secondary); opacity: 1; }

    .tlc-mark {
      position: absolute;
      left: var(--tlc-railx);
      z-index: 2;
      display: grid;
      place-items: center;
      box-sizing: border-box;
      min-width: 1rem;
      height: 1rem;
      padding: 0;
      transform: translate(-50%, -50%);
      border: var(--oc-border) solid transparent;
      border-radius: var(--oc-radius-sm);
      background: var(--oc-ground-card, var(--oc-ground-panel));
      color: var(--oc-text-primary);
      font-family: var(--font-mono);
      font-size: var(--oc-fs-micro);
      font-variant-numeric: tabular-nums;
      cursor: pointer;
    }

    .tlc-mark[data-kind='cluster'] { padding: 0 calc(var(--oc-space-1) - var(--oc-border)); border-color: var(--oc-line-rule); }
    .tlc-mark:hover,
    .tlc-mark[data-pressed],
    .tlc-mark[aria-pressed='true'] { border-color: var(--oc-text-primary); }

    .tlc-label {
      position: absolute;
      left: calc(var(--tlc-rail) + 0.25rem);
      right: 0;
      display: flex;
      align-items: center;
      gap: var(--oc-space-2);
      height: var(--tlc-row);
      padding: 0 var(--oc-space-1);
      border: var(--oc-border) solid transparent;
      border-radius: var(--oc-radius-sm);
      background: none;
      color: var(--oc-text-secondary);
      font-family: var(--font-mono);
      font-size: var(--oc-fs-micro);
      text-align: left;
      cursor: pointer;
    }

    .tlc-label:hover { background: var(--oc-ground-hover); color: var(--oc-text-primary); }
    .tlc-label[aria-pressed='true'] { border-color: var(--oc-line-rule); color: var(--oc-text-primary); }
    .tlc-label__t { flex: 1 1 auto; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .tlc-label__w { flex: 0 0 auto; color: var(--oc-text-muted); font-variant-numeric: tabular-nums; }

    .tlc-label[data-kind='conversation'] { color: var(--oc-text-primary); letter-spacing: var(--oc-tracking-label); text-transform: uppercase; }
    .tlc-label[data-kind='conversation'][data-current] { color: var(--oc-cyan); }
  }
</style>
