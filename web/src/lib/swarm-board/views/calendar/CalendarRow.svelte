
<script lang="ts">
  import { t } from '../../../i18n/index.svelte';
  import { COLUMNS } from '../../board-types';
  import StatusGlyph from '../../StatusGlyph.svelte';
  import AgentFace from '../../AgentFace.svelte';
  import SentBackGlyph from './SentBackGlyph.svelte';
  import { KINDS, dayFraction, emptyCell, type CalendarDay, type CalendarKind, type DayCell } from './calendar-model';
  import type { BoardData, BoardLane } from '../../board-data.svelte';

  interface Props {
    lane: BoardLane;
    cells: DayCell[];
    faces: number[][];
    days: CalendarDay[];
    dayLabels: string[];
    now: number;
    data: BoardData;
  }
  let { lane, cells, faces, days, dayLabels, now, data }: Props = $props();

  const MAX_FACES = 4;
  const BAR_MAX = 18;
  const GLYPH: Record<Exclude<CalendarKind, 'sent_back'>, (typeof COLUMNS)[number]> = { created: 'todo', started: 'in_progress', review: 'review', approved: 'done' };

  const total = $derived(COLUMNS.reduce((n, c) => n + lane.counts[c], 0));

  function barHeight(n: number, max: number): number {
    return n > 0 && max > 0 ? Math.max(2, Math.round((BAR_MAX * n) / max)) : 1;
  }
</script>

<div class="sbcal-row" data-swarm-cal-lane={lane.list_key}>
  <div class="sbcal-lane">
    <div class="sbcal-lane-name">{lane.name}</div>
    <div class="sbcal-lane-total">{t('swarm.board.calendar.cards', { count: total })}</div>
    <div class="sbcal-lane-counts">
      {#each COLUMNS as column (column)}
        <span class="sbcal-lane-n" data-swarm-cal-total={column}><StatusGlyph {column} size={12} label={t(`swarm.board.col.${column}`)} />{lane.counts[column]}</span>
      {/each}
    </div>
  </div>
  {#each days as day, i (day.start)}
    {@const cell = cells[i] ?? emptyCell()}
    {@const max = Math.max(...cell.hours)}
    {@const shown = KINDS.filter((k) => cell.counts[k] > 0)}
    {@const here = (faces[i] ?? []).map((id) => data.agent(id)).filter((a) => a !== undefined)}
    <div class="sbcal-cell" class:sbcal-cell--ahead={day.ahead} data-swarm-cal-day={i} data-today={day.today ? 'true' : undefined} data-ahead={day.ahead ? 'true' : undefined}>
      <span class="sbcal-cell-day">{dayLabels[i]}</span>
      {#if day.today}
        <div class="sbcal-now" aria-hidden="true" data-swarm-cal-now style:left="{(dayFraction(day, now) * 100).toFixed(2)}%"></div>
      {/if}
      <div>
        {#if day.ahead}
          <div class="sbcal-quiet">{t('swarm.board.calendar.ahead')}</div>
        {:else if shown.length === 0}
          <div class="sbcal-quiet">{t('swarm.board.calendar.quiet')}</div>
        {:else}
          {#each shown as kind (kind)}
            <div class="sbcal-count" data-swarm-cal-count={kind}>
              {#if kind === 'sent_back'}<SentBackGlyph size={13} />{:else}<StatusGlyph column={GLYPH[kind]} size={13} />{/if}
              <span class="sbcal-n">{cell.counts[kind]}</span>
              <span class="sbcal-kind">{t(`swarm.board.calendar.kind.${kind}`)}</span>
            </div>
          {/each}
        {/if}
      </div>
      {#if here.length > 0}
        <div class="sbcal-faces" data-swarm-cal-faces>
          {#each here.slice(0, MAX_FACES) as agent (agent.id)}
            <AgentFace {agent} working colors={data.colors} looks={data.looks} />
          {/each}
          {#if here.length > MAX_FACES}<span class="sbcal-more">{t('swarm.board.lane.more_faces', { count: here.length - MAX_FACES })}</span>{/if}
        </div>
      {/if}
      <div class="sbcal-hours" role="img" aria-label={t('swarm.board.calendar.hours')} data-swarm-cal-hours>
        {#each cell.hours as n, h (h)}
          <span class="sbcal-bar" class:sbcal-bar--on={n > 0} data-n={n} style:height="{barHeight(n, max)}px"></span>
        {/each}
      </div>
    </div>
  {/each}
</div>

<style>
  @layer components {
    .sbcal-row {
      display: grid;
      grid-template-columns: var(--_lane-w) repeat(var(--_days), minmax(0, 1fr));
    }
    .sbcal-lane {
      min-width: 0;
      padding: 12px 16px 12px 0;
      box-shadow: 0 1px 0 var(--oc-line-rule);
    }
    .sbcal-lane-name {
      overflow: hidden;
      color: var(--oc-text-bright);
      font-size: var(--oc-fs-title);
      font-weight: 600;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .sbcal-lane-total {
      margin: 2px 0 8px;
      color: var(--oc-text-muted);
      font-size: var(--oc-fs-body);
    }
    .sbcal-lane-counts {
      display: flex;
      flex-wrap: wrap;
      gap: 12px;
    }
    .sbcal-lane-n {
      display: inline-flex;
      align-items: center;
      gap: 5px;
      color: var(--oc-text-secondary);
      font-size: var(--oc-fs-body);
    }
    /* box-shadow */
    .sbcal-cell {
      position: relative;
      display: flex;
      flex-direction: column;
      justify-content: space-between;
      min-width: 0;
      min-height: 128px;
      padding: 12px 10px 10px;
      box-shadow: 1px 0 0 var(--oc-line-rule), 0 1px 0 var(--oc-line-rule);
    }
    .sbcal-cell--ahead {
      background: repeating-linear-gradient(135deg, transparent 0, transparent 6px, var(--oc-line-faint) 6px, var(--oc-line-faint) 7px);
    }
    .sbcal-cell-day {
      display: none;
      margin-bottom: 6px;
      color: var(--oc-text-muted);
      font-size: var(--oc-fs-label);
      letter-spacing: 0.1em;
      text-transform: uppercase;
    }
    .sbcal-faces {
      display: flex;
      justify-content: flex-end;
      align-items: center;
      gap: 4px;
      margin-top: 6px;
    }
    .sbcal-more {
      color: var(--oc-text-muted);
      font-size: var(--oc-fs-label);
    }
    .sbcal-now {
      position: absolute;
      top: 0;
      bottom: 0;
      border-left: 1px solid var(--oc-text-secondary);
      pointer-events: none;
    }
    .sbcal-count {
      display: flex;
      align-items: center;
      gap: 6px;
      height: 22px;
    }
    .sbcal-n {
      min-width: 16px;
      color: var(--oc-text-bright);
      font-weight: 600;
    }
    .sbcal-kind {
      overflow: hidden;
      color: var(--oc-text-secondary);
      font-size: var(--oc-fs-body);
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .sbcal-quiet {
      height: 22px;
      color: var(--oc-text-muted);
      font-size: var(--oc-fs-body);
    }
    .sbcal-hours {
      display: flex;
      align-items: flex-end;
      gap: 1px;
      height: 20px;
      margin-top: 10px;
    }
    .sbcal-bar {
      width: 3px;
      background: var(--oc-line-faint);
    }
    .sbcal-bar--on {
      background: var(--oc-cyan);
    }
    @container swarm-calendar (max-width: 720px) {
      .sbcal-row {
        grid-template-columns: minmax(0, 1fr);
      }
      .sbcal-cell {
        min-height: 0;
        box-shadow: 0 1px 0 var(--oc-line-rule);
      }
      .sbcal-cell-day {
        display: block;
      }
    }
  }
</style>
