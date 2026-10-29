<script lang="ts">
  import { untrack } from 'svelte';
  import type { CellProps } from '../../lib/cell';
  import RunChartTable from '../../ui/RunChartTable.svelte';
  import type { ColumnSpec } from '../../engine/types';
  import { t } from '../../../lib/i18n/index.svelte';
  import Button from '../../../lib/base/Button.svelte';
  import { taskManagerAddonOn } from '../../../lib/task-manager-schedules/task-manager-addon.svelte';
  import { acquireSent, releaseSent, type Sent } from '../../api/sent.svelte';
  import type { Resource } from '../../api/poll.svelte';
  import { clock, startClock } from '../../lib/frozen-clock.svelte';
  import { agoWords, columnsFor } from '../../lib/run-chart';
  import { compact } from '../../lib/format';
  import { outboxView } from '../../../lib/outbox/outbox.svelte';
  import { discard, retryNow, startOutbox } from '../../../lib/outbox/outbox';
  import { copyText, download, exportText } from '../../../lib/outbox/outbox-export';
  import { localRows, SENT_COLUMNS, sentRows, type SentRow } from './sent-model';
  import { MARK_KEYS } from './model';
  import OutboxRows from './OutboxRows.svelte';

  let { width, phone = false, limit = null }: CellProps = $props();

  let feed = $state.raw<Resource<Sent> | null>(null);
  let byHand = $state('');
  let copied = $state(false);

  const taskManagerOn = $derived(taskManagerAddonOn());

  $effect(() => {
    if (!taskManagerOn) return;
    feed = untrack(() => acquireSent());
    return () => {
      untrack(() => releaseSent());
      feed = null;
    };
  });

  $effect(() => startClock());
  $effect(() => startOutbox());

  const nowMs = $derived.by(() => {
    void clock.now;
    return Date.now();
  });

  const local = $derived(localRows(outboxView.entries, nowMs, t));
  const rows = $derived(sentRows(feed?.data?.sends ?? [], nowMs / 1000, t));
  const shownColumns = $derived<ColumnSpec[]>(columnsFor(SENT_COLUMNS, width, phone));
  const failedCount = $derived(local.filter((row) => row.failed).length);
  const view = $derived<'loading' | 'unknown' | 'ready'>(!taskManagerOn || feed?.data ? 'ready' : feed && feed.status !== 'loading' ? 'unknown' : 'loading');

  async function copyOrShow(text: string): Promise<void> {
    byHand = '';
    copied = false;
    if (await copyText(text)) copied = true;
    else byHand = text;
  }

  function selectAll(node: HTMLTextAreaElement): void {
    node.focus();
    node.select();
  }

  function copyOne(id: string): void {
    const entry = outboxView.entries.find((e) => e.id === id);
    if (entry) void copyOrShow(exportText([entry]));
  }
</script>

{#snippet rowCell(row: SentRow, column: ColumnSpec, _index: number)}
  {#if column.key === 'what'}
    <span class="oc-rc-name">
      <span class="oc-rc-mark" data-mark={row.mark} title={t(MARK_KEYS[row.mark])} aria-hidden="true"></span>
      <bdi class="oc-rc-name-text">{row.what}</bdi>
      <span class="oc-visually-hidden" data-outcome-words>{t(MARK_KEYS[row.mark])}</span>
    </span>
  {:else if column.key === 'where'}
    <bdi class="oc-rc-area">{row.where}</bdi>
  {:else if column.key === 'session'}
    <bdi class="oc-rc-area" data-sent-session>{row.session}</bdi>
  {:else if column.key === 'tell'}
    <span class="oc-rc-area" data-sent-tell>{row.tell}</span>
  {:else if column.key === 'ago'}
    <span class="oc-rc-muted">{agoWords(row.agoSeconds)}</span>
  {/if}
{/snippet}

<div class="oc-rc" data-sent-monitor data-view={view}>
  <div class="oc-rc-bar oc-rc-bar--split">
    <span class="oc-rc-line" data-sent-summary>{t('opscenter.sent.summary', { local: compact(local.length), failed: compact(failedCount) })}</span>
    <span class="oc-ob-keys">
      <Button size="sm" data-sent-key="copy-all" disabled={local.length === 0} onclick={() => void copyOrShow(exportText(outboxView.entries))}>{t('opscenter.sent.key.copy_all')}</Button>
      <Button size="sm" data-sent-key="download" disabled={local.length === 0} onclick={() => download(outboxView.entries)}>{t('opscenter.sent.key.download')}</Button>
    </span>
  </div>
  {#if !outboxView.stored && local.length > 0}
    <p class="oc-rc-notice" data-tone="bad" data-sent-no-storage role="status">{t('opscenter.sent.no_storage')}</p>
  {/if}
  {#if copied}<p class="oc-rc-notice" data-sent-copied role="status">{t('opscenter.sent.copied')}</p>{/if}
  {#if byHand}
    <div class="oc-ob-copy" data-sent-by-hand>
      <p class="oc-rc-notice">{t('opscenter.sent.copy_by_hand')}</p>
      <textarea class="oc-ob-text" readonly rows="6" value={byHand} use:selectAll></textarea>
    </div>
  {/if}
  <div class="oc-rq">
    <OutboxRows rows={local} onretry={(id) => void retryNow(id)} oncopy={copyOne} ondiscard={discard} />
    {#if taskManagerOn}
      <section class="oc-rq-section" data-sent-section="sent">
        <h4 class="oc-rq-head">
          <span>{t('opscenter.sent.head')}</span>
          <span class="oc-rq-count" data-rq-count>{compact(rows.length)}</span>
        </h4>
      </section>
    {/if}
  </div>
  {#if !taskManagerOn}
    <p class="oc-rc-notice" data-sent-huddle-off>{t('opscenter.sent.task_manager_off')}</p>
  {:else if view === 'ready'}
    {#if rows.length > 0}
      <div data-sent-chart>
        <RunChartTable columns={shownColumns} {rows} {limit} {phone} cell={rowCell} />
      </div>
    {:else}
      <p class="oc-rc-notice" data-sent-none>{t('opscenter.sent.none')}</p>
    {/if}
  {:else}
    <p class="oc-rc-notice" data-sent-note={view} data-tone={view === 'unknown' ? 'bad' : undefined} role="status">{t(`opscenter.sent.${view}`)}</p>
  {/if}
</div>
