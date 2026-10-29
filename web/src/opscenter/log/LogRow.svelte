<script lang="ts">
  import Button from '../../lib/base/Button.svelte';
  import IconButton from '../../lib/base/IconButton.svelte';
  import { t } from '../../lib/i18n/index.svelte';
  import type { LogRecord } from './types';

  interface Props {
    record: LogRecord;
    expanded: boolean;
    rowPx: number;
    onExpand: (id: string) => void;
    onField: (key: string, value: string, exclude: boolean) => void;
    onCopy: (record: LogRecord) => void;
    onMeasure: (id: string, px: number) => void;
  }

  const { record, expanded, rowPx, onExpand, onField, onCopy, onMeasure }: Props = $props();

  let height = $state(0);

  $effect(() => {
    if (expanded && height > 0) onMeasure(record.id, height);
  });

  const fields = $derived(Object.entries(record.fields));
  const json = $derived(
    expanded
      ? JSON.stringify({ timestamp: record.timestamp, level: record.level, source: record.source, event: record.event, ...record.fields }, null, 2)
      : '',
  );

  function clock(iso: string): string {
    const m = /T(\d{2}:\d{2}:\d{2}(?:\.\d{1,3})?)/.exec(iso);
    return m ? (m[1] as string) : iso;
  }
</script>

<div class="oc-lv-rec" data-log-row data-level={record.level} data-traceback={record.traceback ? '' : undefined}
  data-expanded={expanded ? '' : undefined} bind:offsetHeight={height} style:height={expanded ? undefined : `${rowPx}px`}>
  <div class="oc-lv-row">
    <IconButton label={t(expanded ? 'opscenter.log.collapse' : 'opscenter.log.expand')} aria-expanded={expanded}
      onclick={() => onExpand(record.id)} data-log-expand>{expanded ? '-' : '+'}</IconButton>
    <span class="oc-lv-time" class:oc-lv-time--approx={record.approx_time} data-log-time-approx={record.approx_time ? '' : undefined}
      title={record.approx_time ? t('opscenter.log.time_approx') : undefined}>{record.approx_time ? '~' : ''}{clock(record.timestamp)}</span>
    <span class="oc-lv-tag">{t(`opscenter.log.level.${record.level}`)}</span>
    <span class="oc-lv-source">{record.source}</span>
    <span class="oc-lv-text">
      <bdi class="oc-lv-event">{record.event}</bdi>
      {#if record.lines.length}<span class="oc-lv-more">{t('opscenter.log.more', { count: record.lines.length })}</span>{/if}
      {#each fields as [key, value] (key)}
        <Button size="sm" data-log-field={key}
          onclick={(event) => onField(key, value, event.altKey)}>{key}={value}</Button>
      {/each}
    </span>
    <Button size="sm" variant="quiet" onclick={() => onCopy(record)} data-log-copy>{t('opscenter.log.copy')}</Button>
  </div>
  {#if expanded}
    <pre class="oc-lv-json" data-log-json>{json}</pre>
    {#if record.lines.length}
      <pre class="oc-lv-lines" data-log-lines>{record.lines.join('\n')}</pre>
    {/if}
    {#if record.dropped_lines}
      <p class="oc-lv-dropped">{t('opscenter.log.lines_dropped', { count: record.dropped_lines })}</p>
    {/if}
  {/if}
</div>
