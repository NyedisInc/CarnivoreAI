
<script module lang="ts">
  import type { DiffRun, DiffSide } from '../logic/diff';
  import type { FaceRun } from '../logic/report-rules';
  import type { ReportSlot } from '../logic/types';

  export type SheetRun = FaceRun & DiffRun & {
    automation_id: string;
    trigger: string;
    attempt?: number | null;
    slot_at: number | null;
    has_report: boolean;
    host?: string | null;
    sessions?: unknown[] | null;
    notes?: { by?: { kind?: string; name?: string } | null } | null;
  };
  export type { DiffSide, ReportSlot };
</script>

<script lang="ts">
  import { setContext } from 'svelte';
  import { t } from '../../i18n/index.svelte';
  import { compare, firstResult, isObj, normalizeSlot, usableReport } from '../logic/diff';
  import { stripAnsi } from '../logic/markdown';
  import { conversationUuid } from '../logic/report-rules';
  import { isLive, statusWord, type Clock } from '../logic/words';
  import Button from '../../base/Button.svelte';
  import Card from '../../base/Card.svelte';
  import State from '../../base/State.svelte';
  import DiffSection from './DiffSection.svelte';
  import RawJson from './RawJson.svelte';
  import ReportBody from './ReportBody.svelte';
  import { REPORT_CTX, type ReportCtx } from './ReportTree.svelte';
  import RunHeader from './RunHeader.svelte';
  import './report.css';

  interface Props {
    run: SheetRun;
    slot: ReportSlot;
    composition: 'pane' | 'reader';
    clock: Clock;
    tz: string;
    now: number;
    prev?: DiffSide | null;
    retryMax?: number;
    sinceNumber?: number | null;
    onRetry?: () => void;
    onFix?: (runId: string, findingId: string) => void;
    onRunNow?: () => void;
    onContinue?: () => void;
    onCancel?: () => void;
    onOpenSession?: () => void;
  }
  let { run, slot, composition, clock, tz, now, prev = null, retryMax = 0, sinceNumber = null, onRetry, onFix, onRunNow, onContinue, onCancel, onOpenSession }: Props = $props();

  const norm = $derived(normalizeSlot(slot));
  const report = $derived(norm.state === 'ready' ? norm.report : null);
  const redrawKey = $derived(norm.state === 'ready' ? norm.report : norm.state);
  const rules = $derived({ clock, tz, now });
  const prevReport = $derived(prev ? (usableReport(prev.slot) ?? null) : null);
  const live = $derived(isLive(run.status));
  const sessions = $derived(run.sessions?.length ?? 0);

  setContext<ReportCtx>(REPORT_CTX, {
    get truncated() {
      return isObj(report) && report.truncated === true;
    },
    get fix() {
      return onFix ? (findingId: string) => onFix(run.run_id, findingId) : null;
    },
  });

  let showAll = $state(false);
  let chgOpen = $state(false);
  const result = $derived(prev ? compare(prev, { run, slot }, { showAll, statusWord }) : firstResult(run));
  const heading = $derived(sinceNumber ?? prev?.run.number ? t('automations.page.report.since_n', { n: sinceNumber ?? prev?.run.number ?? 0 }) : t('automations.page.report.since_prev'));
  const toggleAll = (): void => {
    showAll = !showAll;
  };
</script>

<article class="r-sheet" data-run={run.run_id} data-auto={run.automation_id} data-status={run.status} data-composition={composition}>
  {#if composition === 'pane'}
    <RunHeader {run} {report} {rules} {retryMax} />
  {/if}

  {#if run.error}
    <State kind="error" inline class="r-error" title={t('automations.page.report.error')} hint={stripAnsi(run.error)} />
  {/if}

  <section class="r-body">
    {#key redrawKey}
      {#if norm.state === 'pending'}
        <State kind="loading" inline class="r-empty" data-status="pending" title={t('automations.page.face.loading')} />
      {:else if norm.state === 'unreadable' && norm.reason === 'pruned'}
        <State kind="empty" inline class="r-empty" data-status="cleared" title={t('automations.page.report.cleared')} />
      {:else if norm.state === 'unreadable'}
        <State kind="error" inline class="r-empty" data-status="failed" title={t('automations.page.report.unreadable')} hint={norm.message || undefined}>
          {#snippet actions()}<Button size="sm" data-retry onclick={() => onRetry?.()}>{t('automations.page.try_again')}</Button>{/snippet}
        </State>
      {:else}
        <ReportBody {run} {report} prevReport={prevReport} {rules} {sessions} />
      {/if}
    {/key}
  </section>

  {#if composition === 'reader'}
    <DiffSection {result} {heading} {showAll} onToggleAll={toggleAll} />
  {:else if run.status === 'succeeded' || run.status === 'failed'}
    <Card title={t('automations.page.pane.changes')} meta={result.sentence + (result.base && !result.same ? t('automations.page.diff.vs', { n: result.base.number }) : '')} foldable bind:open={chgOpen} data-chg>
      <DiffSection {result} {showAll} onToggleAll={toggleAll} />
    </Card>
  {/if}

  <RawJson report={norm.state === 'ready' ? norm.report : null} />

  {#if composition === 'pane'}
    {@const convo = !live && conversationUuid(report)}
    {#if true}
      <div class="r-actions pn-acts">
        {#if !live}<Button variant="confirm" size="sm" data-act="run" onclick={() => onRunNow?.()}>{t('automations.page.pane.rerun')}</Button>{/if}
        {#if convo}<Button size="sm" data-act="continue" onclick={() => onContinue?.()}>{t('automations.page.pane.continue')}</Button>{/if}
        {#if sessions}<Button size="sm" data-act="open-session" onclick={() => onOpenSession?.()}>{sessions === 1 ? t('automations.page.pane.open_the_session') : t('automations.page.pane.open_sessions', { n: sessions })}</Button>{/if}
        {#if live}<Button variant="danger" size="sm" data-act="cancel" onclick={() => onCancel?.()}>{t('automations.page.pane.cancel')}</Button>{/if}
      </div>
    {/if}
  {/if}
</article>
