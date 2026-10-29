<script lang="ts" module>
  import { defineWidget } from '../../widgets/shell/define-widget.svelte';

  export const ACTIVITY_LOG_WIDGET = defineWidget({ id: 'core.activity-log', scope: 'global', actions: [], settings: { showSystem: true }, state: {} });
</script>

<script lang="ts">
  import type { CellProps } from '../../lib/cell';
  import { atLeast } from '../../lib/states';
  import { activity, seeded, auth, type ActivityEntry } from '../../api';
  import { newestFirst } from '../../api/activity-order';
  import { activity as demoLines } from '../../data/activity';
  import { columns, sourceFullMinPx, rowHeight, ROW_PAD_LEFT, ROW_PAD_RIGHT, ROW_GAP } from './meta';
  import { t } from '../../../lib/i18n/index.svelte';
  import State from '../../../lib/base/State.svelte';
  import WidgetShell from '../../widgets/shell/WidgetShell.svelte';
  import { useWidget } from '../../widgets/shell/define-widget.svelte';

  let props: CellProps = $props();
  const { meta } = $derived(props);
  const phone = $derived(props.phone ?? false);
  const limit = $derived(props.limit ?? null);

  const widget = useWidget(ACTIVITY_LOG_WIDGET, () => props);
  const widthState = $derived(widget.widthState);
  const heightState = $derived(widget.heightState);

  const timeCol = columns.find((column) => column.key === 'time')!;
  const tagCol = columns.find((column) => column.key === 'tag')!;
  const messageCol = columns.find((column) => column.key === 'message')!;
  const sourceCol = columns.find((column) => column.key === 'source')!;

  const showsTime = $derived(atLeast(meta.widthStates, widthState, 'time'));
  const showsTag = $derived(atLeast(meta.widthStates, widthState, 'tag'));
  const showsSeconds = $derived(atLeast(meta.widthStates, widthState, 'seconds'));
  const showsSource = $derived(atLeast(meta.widthStates, widthState, 'source'));
  const isFull = $derived(atLeast(meta.widthStates, widthState, 'full'));

  const shown = $derived.by(() => {
    const out = [];
    if (showsTime) out.push(timeCol);
    if (showsTag) out.push(tagCol);
    out.push(messageCol);
    if (showsSource) out.push(isFull ? { ...sourceCol, minPx: sourceFullMinPx } : sourceCol);
    return out;
  });

  const tracks = $derived(shown.map((column) => `minmax(${column.minPx}px, ${column.weight}fr)`).join(' '));

  const lineCount = $derived.by(() => {
    if (heightState === 'title') return 0;
    if (heightState === 'lines-1') return 1;
    if (heightState === 'lines-2') return 2;
    if (heightState === 'lines-5') return 5;
    if (heightState === 'lines-8') return 8;
    return ordered.length;
  });

  const ordered = $derived(
    newestFirst(activity.lines).filter((line) => showSystem || line.tag !== 'system'),
  );

  const showSystem = $derived(widget.setting('showSystem'));

  const rows = $derived(ordered.slice(0, limit ?? lineCount));

  const highlightsByLine = new Map<string, readonly (readonly [number, number])[]>();
  for (const line of demoLines) {
    if (line.highlights) highlightsByLine.set(`${line.time}|${line.message}`, line.highlights);
  }

  interface Segment {
    text: string;
    hit: boolean;
  }

  function segmentsOf(row: ActivityEntry): Segment[] {
    const ranges = (highlightsByLine.get(`${row.time}|${row.message}`) ?? [])
      .map(([from, to]) => [Math.max(0, from), Math.min(row.message.length, to)] as const)
      .filter(([from, to]) => to > from)
      .sort((a, b) => a[0] - b[0]);
    if (!ranges.length) return [{ text: row.message, hit: false }];
    const out: Segment[] = [];
    let at = 0;
    for (const [from, to] of ranges) {
      if (from > at) out.push({ text: row.message.slice(at, from), hit: false });
      out.push({ text: row.message.slice(from, to), hit: true });
      at = to;
    }
    if (at < row.message.length) out.push({ text: row.message.slice(at), hit: false });
    return out;
  }

  function timeText(value: string): string {
    return showsSeconds ? value : value.slice(0, 5);
  }

  /* there is nothing */
  const notice = $derived.by((): string | null => {
    if (ordered.length > 0) return null;
    if (!seeded.loaded) return t('opscenter.activity.loading');
    if (seeded.status === 'error') return seeded.error ?? t('opscenter.activity.error');
    if (seeded.status === 'unavailable') return t('opscenter.activity.unavailable');
    if (seeded.status === 'signed-out' || auth.state === 'signed-out') {
      return t('opscenter.activity.signed_out');
    }
    return t('opscenter.activity.empty');
  });

</script>

<WidgetShell {widget}>
<div class="oc-log">
  {#if notice}
    {#if heightState !== 'title'}
      <State inline title={notice} />
    {/if}
  {:else if phone}
    
    <div class="oc-log-pbody">
      {#each rows as row (row.id)}
        <div class="oc-log-prow" data-row={row.id}>
          <span class="oc-log-ptime">{row.time.slice(0, 5)}</span>
          <span
            class="oc-log-pdot"
            role="img"
            aria-label={row.tag}
            title={row.tag}
            style={`background: var(--oc-tag-${row.tag})`}
          ></span>
          <span class="oc-log-pmsg">{row.message}</span>
        </div>
      {/each}
    </div>
  {:else}
  <div class="oc-log-body" style={`--oc-log-rowh: ${rowHeight}px; --oc-log-padl: ${ROW_PAD_LEFT}px; --oc-log-padr: ${ROW_PAD_RIGHT}px; --oc-log-gap: ${ROW_GAP}px`}>
    {#each rows as row (row.id)}
      <div class="oc-log-row" data-row={row.id} style={`grid-template-columns: ${tracks}`}>
        {#if showsTime}
          <span class="oc-log-cell oc-log-time" data-col="time">
            {timeText(row.time)}
            {#if showsTag}<span class="oc-log-divider" aria-hidden="true"></span>{/if}
          </span>
        {/if}
        {#if showsTag}
          <span class="oc-log-cell oc-log-tag" data-col="tag" style={`color: var(--oc-tag-${row.tag})`}>{t('opscenter.activity.tag', { tag: row.tag })}</span
          >
        {/if}
        {#if segmentsOf(row).length === 1}
          {@const parts = segmentsOf(row)}
          
          <span class="oc-log-cell oc-log-message" data-col="message" class:oc-log-message-hit={parts[0]?.hit}>
            {parts[0]?.text}
          </span>
        {:else}
          <span class="oc-log-cell oc-log-message" data-col="message">
            {#each segmentsOf(row) as segment}<span class="oc-log-run" class:oc-log-message-hit={segment.hit}>{segment.text}</span>{/each}
          </span>
        {/if}
        {#if showsSource}
          <span class="oc-log-cell oc-log-source" data-col="source">{row.source}</span>
        {/if}
      </div>
    {/each}
  </div>
  {/if}
</div>
</WidgetShell>

<style>
  @layer components {
    .oc-log {
      display: flex;
      flex-direction: column;
      min-width: 0;
      min-height: 0;
      height: 100%;
    }


    .oc-log-body {
      flex: 1;
      min-height: 0;
      min-width: 0;
      overflow-y: auto;
      overflow-x: hidden;
      padding: calc(var(--oc-space-1) - var(--oc-border)) 0 var(--oc-space-0-5);
    }

    .oc-log-pbody {
      display: flex;
      flex-direction: column;
      min-width: 0;
    }

    .oc-log-prow {
      display: flex;
      align-items: center;
      gap: var(--oc-space-2);
      min-height: var(--oc-tap);
      padding: 0 var(--oc-cell-pad);
      min-width: 0;
    }

    .oc-log-ptime {
      flex: 0 0 auto;
      font-size: var(--oc-fs-label);
      color: var(--oc-text-secondary);
      font-variant-numeric: tabular-nums;
    }

    .oc-log-pdot {
      flex: 0 0 auto;
      width: 8px;
      height: 8px;
      border-radius: 50%;
    }

    .oc-log-pmsg {
      flex: 1 1 auto;
      min-width: 0;
      overflow: hidden;
      white-space: nowrap;
      text-overflow: ellipsis;
      color: var(--oc-text-primary);
      font-size: var(--oc-fs-body);
    }

    .oc-log-row {
      display: grid;
      align-items: center;
      column-gap: var(--oc-log-gap);
      height: var(--oc-log-rowh);
      min-width: 0;
      padding: 0 var(--oc-log-padr) 0 var(--oc-log-padl);
      font-size: var(--oc-fs-body);
    }

    .oc-log-cell {
      min-width: 0;
      overflow: hidden;
      white-space: nowrap;
      text-overflow: ellipsis;
    }

    .oc-log-time {
      display: flex;
      align-items: center;
      justify-content: space-between;
      color: var(--oc-text-secondary);
    }

    .oc-log-divider {
      width: 2px;
      height: 2px;
      border-radius: 1px;
      background: transparent;
      box-shadow:
        0 -4px 0 0 var(--oc-text-dim),
        0 3px 0 0 var(--oc-text-dim);
    }

    .oc-log-tag {
      font-weight: 500;
    }

    .oc-log-message {
      color: var(--oc-text-primary);
    }

    .oc-log-run {
      min-width: 0;
      overflow: hidden;
    }

    .oc-log-message-hit {
      color: var(--oc-green);
    }

    .oc-log-source {
      color: var(--oc-text-dim);
    }
  }
</style>
