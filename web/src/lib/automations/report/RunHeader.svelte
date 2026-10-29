
<script lang="ts">
  import Tag from '../../base/Tag.svelte';
  import { t } from '../../i18n/index.svelte';
  import { isObj } from '../logic/diff';
  import { runMarkName } from '../logic/marks';
  import { REPORT_NEAR_CAP_BYTES } from '../logic/report-cap';
  import { skipReason, bytesWords, countWords, reasonWords, runStatusWord, tookWords } from '../logic/words';
  import type { RuleContext } from '../logic/report-rules';
  import { costLabel } from '../format';
  import { mark } from './ReportTree.svelte';

  interface HeadRun {
    status: string;
    reason: string | null;
    number: number;
    trigger: string;
    attempt?: number | null;
    slot_at: number | null;
    started_at: number | null;
    ended_at: number | null;
    skip_count: number | null;
    first_slot_at?: number | null;
    last_slot_at?: number | null;
    cost_usd: number | null;
    has_report: boolean;
    report_bytes: number | null;
    host?: string | null;
    sessions?: unknown[] | null;
    notes?: { by?: { kind?: string; name?: string } | null } | null;
  }
  let { run, report = null, rules, retryMax = 0 }: { run: HeadRun; report?: unknown; rules: RuleContext; retryMax?: number } = $props();

  const reason = $derived(run.status === 'skipped' ? skipReason(run, rules.tz) : run.reason ? reasonWords(run.reason) : '');
  const word = $derived(runStatusWord(run));

  const trigger = $derived.by(() => {
    const max = retryMax + 1;
    const attempt = run.attempt ?? 1;
    const by = run.notes?.by;
    if (run.trigger === 'run_now') {
      if (!by) return t('automations.page.head.trigger.run_now');
      return by.kind === 'mcp' ? t('automations.page.head.trigger.run_now_mcp') : t('automations.page.head.trigger.run_now_by', { name: by.name || t('automations.page.head.you') });
    }
    if (run.trigger === 'catch_up') return t('automations.page.head.trigger.catch_up');
    if (run.trigger === 'retry') return t('automations.page.head.trigger.retry', { a: attempt, n: max });
    return max > 1 ? t('automations.page.head.trigger.scheduled_attempt', { a: attempt, n: max }) : t('automations.page.head.trigger.scheduled');
  });

  const timing = $derived.by(() => {
    const clock = rules.clock;
    const slot = run.slot_at ? t('automations.page.head.slot', { when: clock.when(run.slot_at) }) : '';
    if (run.status === 'skipped') return slot;
    const parts: string[] = [];
    if (slot) parts.push(slot);
    if (run.started_at && (run.status === 'running' || run.status === 'waiting_on_you')) parts.push(t('automations.page.head.started', { when: clock.rel(run.started_at, rules.now) }));
    else if (run.started_at) {
      parts.push(t('automations.page.head.started', { when: clock.hms12(run.started_at) }));
      const took = tookWords(run);
      if (took) parts.push(t('automations.page.empty.took', { took }));
    } else if (run.status === 'claimed') parts.push(t('automations.page.head.waiting_slot'));
    if (run.slot_at && run.started_at && run.trigger === 'schedule' && run.started_at - run.slot_at > 60) parts.push(t('automations.page.head.late', { n: Math.round((run.started_at - run.slot_at) / 60) }));
    return parts.join(', ');
  });

  const output = $derived.by(() => {
    if ((run.report_bytes ?? 0) > 0) return (run.report_bytes ?? 0) >= REPORT_NEAR_CAP_BYTES ? t('automations.page.reader.size_cap', { size: bytesWords(run.report_bytes) }) : bytesWords(run.report_bytes);
    if (run.status === 'succeeded') return run.has_report ? t('automations.page.head.output_zero') : t('automations.page.head.output_none');
    return null;
  });
  const exit = $derived(isObj(report) && typeof report.exit_code === 'number' ? String(report.exit_code) : null);
  const sessions = $derived(run.sessions?.length ?? 0);
</script>

{#snippet chip(label: string | null, value: string)}
  <Tag>{#if label}<i>{label}</i>{' '}{/if}{value}</Tag>
{/snippet}

<header class="r-head" data-status={run.status}>
  <div class="r-line1">
    <span class="r-stl">{@render mark(runMarkName(run.status), 14, word)}<b class="r-st">{word}</b></span>
    {#if reason}<span class="r-reason">{reason}</span>{/if}
    <span class="r-num ap-num">#{run.number}</span>
  </div>
  <div class="r-chips-line">
    {@render chip(null, trigger)}
    {#if timing}{@render chip(null, timing)}{/if}
    {@render chip(null, costLabel(run.cost_usd))}
    {#if output !== null}{@render chip(t('automations.page.head.output'), output)}{/if}
    {#if exit !== null}{@render chip(t('automations.page.head.exit'), exit)}{/if}
    {#if sessions}{@render chip(null, countWords('automations.page.count.session', sessions))}{/if}
    {@render chip(t('automations.page.head.on'), run.host || t('automations.page.reader.computer_not_recorded'))}
  </div>
</header>
