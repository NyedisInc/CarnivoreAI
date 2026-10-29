
<script lang="ts">
  import { t } from '../../i18n/index.svelte';
  import { readTab, writeTab } from '../../../opscenter/ui/tab-memory';
  import { COLUMNS, type CardCounts } from '../board-types';
  import BoardKey from './calendar/BoardKey.svelte';
  import CalendarRow from './calendar/CalendarRow.svelte';
  import { createEventWindow } from './calendar/card-events.svelte';
  import { SCALES, bucketEvents, calendarDays, emptyCell, facesByDay, groupLanes, type CalendarScale } from './calendar/calendar-model';
  import type { BoardViewProps } from '../view-props';

  let { data }: BoardViewProps = $props();

  const SCALE_KEY = 'swarm-board-calendar-scale';
  let scale = $state(readTab(SCALE_KEY, SCALES, 'week') as CalendarScale);

  const today = $derived(new Date(new Date(data.now).toDateString()).getTime());
  const days = $derived(calendarDays(scale, today));
  const first = $derived(days[0]!);
  const last = $derived(days[days.length - 1]!);
  const range = $derived({ since: first.start / 1000, until: last.end / 1000 });
  const events = createEventWindow(data, () => range);

  const searchIds = $derived(data.search ? new Set(data.lanes.flatMap((lane) => COLUMNS.flatMap((c) => lane.columns[c].map((card) => card.id)))) : null);
  const laneKeys = $derived(new Set(data.lanes.map((lane) => lane.list_key)));
  const buckets = $derived(bucketEvents(events.rows, days, (row) => (laneKeys.has(row.list_key) ? row.list_key : null), (row) => !searchIds || searchIds.has(row.item_id)));
  const shownLanes = $derived(data.lanes.filter((lane) => COLUMNS.some((c) => lane.counts[c] > 0) || buckets.has(lane.list_key)));
  const groups = $derived(groupLanes(shownLanes));
  const totals = $derived(Object.fromEntries(COLUMNS.map((c) => [c, data.lanes.reduce((n, lane) => n + lane.counts[c], 0)])) as CardCounts);
  const sentBack = $derived([...buckets.values()].reduce((n, cells) => n + cells.reduce((m, cell) => m + cell.counts.sent_back, 0), 0));

  function dayLabel(date: Date): string {
    return t('swarm.board.calendar.day_label', { weekday: t(`swarm.board.calendar.wd.${date.getDay()}`), date: String(date.getDate()).padStart(2, '0') });
  }
  function longLabel(date: Date): string {
    return t('swarm.board.calendar.long_label', { weekday: t(`swarm.board.calendar.wd.${date.getDay()}`), month: t(`swarm.board.calendar.mo.${date.getMonth()}`),
      date: String(date.getDate()).padStart(2, '0') });
  }
  const labels = $derived(days.map((d) => dayLabel(d.date)));
  const subtitle = $derived(scale === 'week' ? t('swarm.board.calendar.sub.week', { day: longLabel(first.date) })
    : scale === 'three' ? t('swarm.board.calendar.sub.three', { from: longLabel(first.date), to: longLabel(last.date) })
    : t('swarm.board.calendar.sub.day', { day: longLabel(first.date) }));

  function pickScale(next: CalendarScale): void {
    scale = next;
    writeTab(SCALE_KEY, next);
  }
</script>

<div class="sbcal" data-swarm-view="calendar" data-swarm-cal-scale={scale} style:--_days={days.length}>
  <div class="sbcal-head">
    <span class="sbcal-title">{t('swarm.board.calendar.title')}</span>
    <span class="sbcal-sub" data-swarm-cal-sub>{subtitle}</span>
    <div class="sbcal-scale" role="group" aria-label={t('swarm.board.calendar.scale')}>
      <span class="sbcal-label">{t('swarm.board.calendar.scale')}</span>
      {#each SCALES as s (s)}
        <button type="button" class="sbcal-key" aria-pressed={scale === s} data-swarm-cal-scale-key={s} onclick={() => pickScale(s)}>{t(`swarm.board.calendar.scale.${s}`)}</button>
      {/each}
    </div>
  </div>
  <div class="sbcal-days">
    <div></div>
    {#each days as day, i (day.start)}
      <div class="sbcal-day" data-swarm-cal-head={i}>{labels[i]}{#if day.today}<span class="sbcal-today">{t('swarm.board.calendar.today')}</span>{/if}</div>
    {/each}
  </div>
  {#if events.status === 'error'}
    <p class="sbcal-note sbcal-note--bad" data-swarm-cal-error>{t('swarm.board.calendar.events_error', { error: events.error ?? '' })}</p>
  {:else if events.truncated}
    <p class="sbcal-note" data-swarm-cal-truncated>{t('swarm.board.calendar.truncated', { count: events.rows.length })}</p>
  {/if}
  {#if shownLanes.length === 0 && data.status === 'ok'}
    <p class="sbcal-note" data-swarm-board-empty>{data.search ? t('swarm.board.no_match', { q: data.search }) : t('swarm.board.empty')}</p>
  {/if}
  {#each groups as group (group.company ?? '')}
    <div class="sbcal-group" data-swarm-cal-group>
      {#if group.company}{group.company}<span class="sbcal-group-kind">{t('swarm.board.calendar.company')}</span>{:else}{t('swarm.board.calendar.lists')}{/if}
    </div>
    {#each group.lanes as lane (lane.list_key)}
      <CalendarRow {lane} cells={buckets.get(lane.list_key) ?? days.map(() => emptyCell())} faces={facesByDay(lane, days)} {days} dayLabels={labels} now={data.now} {data} />
    {/each}
  {/each}
  <BoardKey {totals} {sentBack} />
</div>

<style>
  @layer components {
    .sbcal {
      --_lane-w: 200px;
      container: swarm-calendar / inline-size;
      min-width: 0;
      padding: 28px 0 var(--oc-space-5);
      font-family: var(--font-mono);
    }
    .sbcal-head {
      display: flex;
      flex-wrap: wrap;
      align-items: baseline;
      gap: 12px 20px;
      margin-bottom: 18px;
    }
    .sbcal-title {
      color: var(--oc-text-bright);
      font-size: var(--oc-fs-title);
      font-weight: 600;
    }
    .sbcal-sub,
    .sbcal-label {
      color: var(--oc-text-muted);
      font-size: var(--oc-fs-label);
      letter-spacing: 0.14em;
      text-transform: uppercase;
    }
    .sbcal-scale {
      display: flex;
      align-items: center;
      gap: 4px;
      margin-left: auto;
    }
    .sbcal-label {
      margin-right: 4px;
    }
    .sbcal-key {
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
    .sbcal-key:hover {
      color: var(--oc-text-bright);
    }
    .sbcal-key[aria-pressed='true'] {
      --_bd: var(--oc-cyan);
      background: color-mix(in srgb, var(--oc-cyan) 12%, transparent);
      color: var(--oc-cyan);
    }
    .sbcal-days {
      display: grid;
      grid-template-columns: var(--_lane-w) repeat(var(--_days), minmax(0, 1fr));
      box-shadow: 0 1px 0 var(--oc-line-rule);
    }
    .sbcal-day {
      padding: 0 12px 8px;
      color: var(--oc-text-muted);
      font-size: var(--oc-fs-label);
      letter-spacing: 0.1em;
      text-transform: uppercase;
      white-space: nowrap;
    }
    .sbcal-today {
      margin-left: 8px;
      color: var(--oc-cyan);
    }
    .sbcal-group {
      display: flex;
      align-items: center;
      gap: 10px;
      height: 40px;
      margin-top: 10px;
      color: var(--oc-text-secondary);
      font-size: var(--oc-fs-label);
      letter-spacing: 0.14em;
      text-transform: uppercase;
    }
    .sbcal-group-kind {
      color: var(--oc-text-muted);
      font-size: var(--oc-fs-body);
      letter-spacing: 0;
      text-transform: none;
    }
    .sbcal-note {
      margin: 14px 0 0;
      color: var(--oc-text-muted);
      font-size: var(--oc-fs-body);
    }
    .sbcal-note--bad {
      color: var(--oc-coral);
    }
    @container swarm-calendar (max-width: 720px) {
      .sbcal-days {
        display: none;
      }
      .sbcal-scale {
        margin-left: 0;
      }
    }
  }
</style>
