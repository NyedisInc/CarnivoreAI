
<script lang="ts">
  import { onMount } from 'svelte';
  import Button from '../../base/Button.svelte';
  import Tag from '../../base/Tag.svelte';
  import { t } from '../../i18n/index.svelte';
  import { subscribe } from '../../../opscenter/api/events.svelte';
  import * as api from '../api';
  import { costLabel } from '../format';
  import Mark from '../Mark.svelte';
  import { kindWords, runNow } from '../list-state.svelte';
  import { compare, firstResult, usableReport, type DiffSide } from '../logic/diff';
  import { conversationUuid } from '../logic/report-rules';
  import type { FeedRun, ReportSlot, RunDelivered } from '../logic/types';
  import { bytesWords, isLive, reasonWords, runStatusWord, runTime, skipReason, statusWord, type Clock } from '../logic/words';
  import RunSheet, { type SheetRun } from '../report/RunSheet.svelte';
  import { readerFacts, whatRan, type ReaderRun } from './feed-model';
  import { attachmentHref, cancelRun, carryOn, fixIt, openRunSessions } from '../run-actions';

  type Props = {
    run: FeedRun;
    automation: api.Automation | undefined;
    automationName: string;
    slot: ReportSlot;
    prev: DiffSide | null;
    clock: Clock;
    tz: string;
    now: number;
    retryMax: number;
    onBack: () => void;
    onPrev: () => void;
    onNext: () => void;
    onNextChanged: () => void;
    onOpenAuto: () => void;
    onRetryReport: () => void;
  };
  let { run, automation, automationName, slot, prev, clock, tz, now, retryMax, onBack, onPrev, onNext, onNextChanged, onOpenAuto, onRetryReport }: Props = $props();

  const live = $derived(isLive(run.status));
  const report = $derived(usableReport(slot) ?? null);
  const convo = $derived(!live && conversationUuid(report));
  const reason = $derived(run.status === 'skipped' ? skipReason(run, tz) : run.reason ? reasonWords(run.reason) : '');
  const result = $derived(prev ? compare(prev, { run: run as SheetRun, slot }, { statusWord }) : firstResult(run as SheetRun));
  const since = $derived(prev ? t('automations.page.reader.since', { n: prev.run.number, sentence: result.sentence }) : result.sentence);
  const facts = $derived(readerFacts(run as ReaderRun, clock, tz, retryMax, costLabel(run.cost_usd)));
  const what = $derived(automation ? whatRan(automation.target, kindWords(automation.target.kind)) : null);

  const n = (x: number): string => x.toLocaleString('en-US');
  const tokens = $derived(
    run.usage ? t('automations.page.reader.tokens_value', { total: n(run.usage.total), input: n(run.usage.input), output: n(run.usage.output), cache: n(run.usage.cache) }) : t('automations.page.reader.not_measured'),
  );

  let detail = $state<RunDelivered | null>(null);
  const delivered = $derived(detail ?? run.delivered);
  const deliveredText = $derived.by(() => {
    if (!delivered) return automation && !automation.delivery.notify ? t('automations.page.reader.delivered_off') : t('automations.page.reader.delivered_none');
    const state = delivered.state ? t(`automations.page.reader.delivered.${delivered.state}`) : '';
    return t('automations.page.reader.delivered_value', { at: clock.hms24(delivered.at), state }).replace(/,\s*$/, '');
  });
  const alertKey = $derived(run.delivered?.alert_key ?? null);
  const leftOut = $derived(((run.notes?.attachments_left_out as { name: string; reason: string }[] | undefined) ?? []).filter((x) => x && x.name));

  async function readDetail(): Promise<void> {
    try {
      detail = (await api.getRun(run.run_id)).delivered ?? null;
    } catch {
    }
  }

  onMount(() => {
    let timer: ReturnType<typeof setTimeout> | null = null;
    const again = (frame: { key?: unknown }): void => {
      if (!alertKey || frame.key !== alertKey) return;
      if (timer) clearTimeout(timer);
      timer = setTimeout(() => void readDetail(), 500);
    };
    if (alertKey) void readDetail();
    const off = ['app_alert.raised', 'app_alert.updated', 'app_alert.resolved'].map((kind) => subscribe(kind, (frame) => again(frame as unknown as { key?: unknown })));
    return () => {
      off.forEach((stop) => stop());
      if (timer) clearTimeout(timer);
    };
  });
</script>

<div class="ap-rd" data-reader data-run={run.run_id} data-auto={run.automation_id} data-status={run.status}>
  <header class="ap-rd-head" data-status={run.status}>
    <div class="ap-rd-kick">
      <Button size="sm" data-dc-back data-act="back" aria-label={t('automations.page.reader.back')} onclick={onBack}>&lt;</Button>
      <Button variant="quiet" data-rd-auto data-act="open-auto" title={t('automations.page.reader.open_auto')} onclick={onOpenAuto}>{automationName || t('automations.page.reader.removed')}</Button>
      <span class="ap-rd-num ap-num">#{run.number}</span>
      <span class="ap-rd-rel">{clock.rel(runTime(run), now)}</span>
    </div>
    <div class="ap-rd-stl">
      <Mark status={run.status} size={18} />
      <h2 class="ap-rd-stw">{runStatusWord(run)}</h2>
      {#if reason}<span class="ap-rd-reason">{reason}</span>{/if}
    </div>
    <p class="ap-rd-since ap-num" data-since>{since}</p>
    <dl class="ap-rd-def">
      {#each facts as [label, value] (label)}
        <div><dt>{t(`automations.page.reader.fact.${label}`)}</dt><dd class="ap-num">{value}</dd></div>
      {/each}
    </dl>
    <div class="ap-rd-strip">
      <Button variant="confirm" size="sm" data-act="run" disabled={!automation} onclick={() => automation && void runNow(automation)}>{t('automations.page.reader.rerun')}</Button>
      {#if convo}<Button size="sm" data-act="continue" onclick={() => void carryOn(run.run_id)}>{t('automations.page.reader.continue')}</Button>{/if}
      {#if live}<Button size="sm" data-act="cancel" onclick={() => void cancelRun(run.run_id)}>{t('automations.page.reader.cancel')}</Button>{/if}
      {#if run.sessions?.length}<Button size="sm" data-act="open-session" onclick={() => openRunSessions(run.sessions)}>{t('automations.page.reader.open_session')}</Button>{/if}
      <Button size="sm" data-act="open-auto" onclick={onOpenAuto}>{t('automations.page.reader.open_automation')}</Button>
      <span class="ap-rd-nav">
        <Button size="sm" data-act="prev" aria-label={t('automations.page.reader.prev_aria')} title="k" onclick={onPrev}>&#8249;</Button>
        <Button size="sm" data-act="next" aria-label={t('automations.page.reader.next_aria')} title="j" onclick={onNext}>&#8250;</Button>
        <Button size="sm" data-act="next-changed" title="u" onclick={onNextChanged}>{t('automations.page.reader.next_changed')}</Button>
      </span>
    </div>
  </header>

  <div class="ap-rd-in">
    {#if what}
      <div class="r-what">
        <span class="r-wk">{what.kind}</span>
        {#if what.text}<code class="r-wt">{what.text}</code>{/if}
        {#each what.params as [label, value] (label)}<Tag><i>{label}</i> {value}</Tag>{/each}
      </div>
    {/if}
    <RunSheet
      run={run as unknown as SheetRun}
      {slot}
      composition="reader"
      {clock}
      {tz}
      {now}
      {prev}
      {retryMax}
      onRetry={onRetryReport}
      onFix={(runId, findingId) => void fixIt(runId, findingId)}
    />
    <section class="r-sec" data-part="record">
      <h3 class="r-h">{t('automations.page.reader.record')}</h3>
      <dl class="r-kv">
        <div><dt>{t('automations.page.reader.tokens')}</dt><dd>{tokens}</dd></div>
        <div><dt>{t('automations.page.reader.delivered')}</dt><dd data-delivered>{deliveredText}</dd></div>
        <div>
          <dt>{t('automations.page.reader.attachments')}</dt>
          <dd data-attachments>
            {#if run.attachments?.length}
              {#each run.attachments as a, i (a.name)}
                <a class="ap-rd-file" href={attachmentHref(run.run_id, a.name)} download={a.name} data-attachment={a.name}>{a.name} ({bytesWords(a.bytes)})</a>{i < run.attachments.length - 1 ? ', ' : ''}
              {/each}
            {:else}
              {t('automations.page.reader.attachments_none')}
            {/if}
            {#each leftOut as x (x.name)}
              <span class="r-note" data-left-out>{t('automations.page.reader.left_out_line', { name: x.name, reason: t(`automations.page.reader.left_out.${x.reason}`) })}</span>
            {/each}
          </dd>
        </div>
      </dl>
    </section>
  </div>
</div>
