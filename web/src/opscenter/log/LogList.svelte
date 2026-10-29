<script lang="ts">
  import { tick } from 'svelte';
  import { t } from '../../lib/i18n/index.svelte';
  import LogRow from './LogRow.svelte';
  import { layout, windowAt } from './virtual';
  import type { LogRecord } from './types';

  interface Props {
    records: readonly LogRecord[];
    expanded: ReadonlySet<string>;
    following: boolean;
    unseen: number;
    onFollow: (following: boolean) => void;
    onExpand: (id: string) => void;
    onField: (key: string, value: string, exclude: boolean) => void;
    onCopy: (record: LogRecord) => void;
  }

  const { records, expanded, following, unseen, onFollow, onExpand, onField, onCopy }: Props = $props();

  const ROW_PX = 22;
  const STICK_SLACK_PX = 24;

  let list = $state<HTMLElement | null>(null);
  let scrollTop = $state(0);
  let viewport = $state(0);
  let heights = $state.raw<Map<string, number>>(new Map());

  const ids = $derived(records.map((r) => r.id));
  const lay = $derived(layout(ids, ROW_PX, heights));
  const total = $derived(lay.offsets[lay.offsets.length - 1] ?? 0);
  const win = $derived(windowAt(lay, scrollTop, viewport || ROW_PX * 40));
  const shown = $derived(records.slice(win.start, win.end));
  const top = $derived(lay.offsets[win.start] ?? 0);
  const bottom = $derived(total - (lay.offsets[win.end] ?? total));

  $effect(() => {
    void total;
    if (!list || !following) return;
    const node = list;
    void tick().then(() => {
      node.scrollTop = node.scrollHeight;
      scrollTop = node.scrollTop;
    });
  });

  $effect(() => {
    const stale = [...heights.keys()].filter((id) => !expanded.has(id));
    if (stale.length) {
      const next = new Map(heights);
      for (const id of stale) next.delete(id);
      heights = next;
    }
  });

  function onScroll(): void {
    if (!list) return;
    scrollTop = list.scrollTop;
    const atEnd = list.scrollHeight - list.scrollTop - list.clientHeight <= STICK_SLACK_PX;
    if (atEnd !== following) onFollow(atEnd);
  }

  function measure(id: string, px: number): void {
    if (heights.get(id) === px) return;
    const next = new Map(heights);
    next.set(id, px);
    heights = next;
  }
</script>

<div class="oc-lv-wrap">
  
  <!-- svelte-ignore a11y_no_noninteractive_tabindex -->
  <div class="oc-lv-list" bind:this={list} bind:clientHeight={viewport} onscroll={onScroll} data-log-list tabindex="0" role="log"
    aria-label={t('opscenter.log.list')}>
    <div style:height={`${top}px`}></div>
    {#each shown as record (record.id)}
      <LogRow {record} expanded={expanded.has(record.id)} rowPx={ROW_PX} {onExpand} {onField} {onCopy} onMeasure={measure} />
    {/each}
    <div style:height={`${bottom}px`}></div>
  </div>
  {#if !following && unseen > 0}
    <button type="button" class="oc-btn oc-btn--sm oc-btn--confirm oc-lv-pill" data-log-jump onclick={() => onFollow(true)}>
      {t('opscenter.log.jump', { count: unseen })}
    </button>
  {/if}
</div>
