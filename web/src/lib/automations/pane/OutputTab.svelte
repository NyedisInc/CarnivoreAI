
<script lang="ts">
  import { t } from '../../i18n/index.svelte';
  import Button from '../../base/Button.svelte';
  import State from '../../base/State.svelte';
  import { openSession, openSessions } from '../../../opscenter/api/host';
  import * as api from '../api';
  import Mark from '../Mark.svelte';
  import { ensureReport, lookup, reports } from '../feed-store.svelte';
  import { runNow } from '../list-state.svelte';
  import { previousIndex } from '../logic/diff';
  import { statusWord } from '../logic/words';
  import { data, pageClock, refresh } from '../page-store.svelte';
  import { refusalText } from '../format';
  import RunSheet, { type SheetRun } from '../report/RunSheet.svelte';
  import { paneSlot, pane, refreshPaneRuns, type PaneRun } from './pane-data.svelte';

  type Props = { automation: api.Automation; shown: PaneRun | null; onStep: (dir: 1 | -1) => void; onNewest: () => void };
  let { automation, shown, onStep, onNewest }: Props = $props();

  const runs = $derived(pane.runs);
  const at = $derived(shown ? runs.findIndex((r) => r.run_id === shown.run_id) : -1);
  const older = $derived(at >= 0 ? (runs[at + 1] ?? null) : null);
  const newer = $derived(at > 0 ? (runs[at - 1] ?? null) : null);
  const total = $derived(automation.newest_number ?? runs[0]?.number ?? 0);
  const prevAt = $derived(shown && at >= 0 ? previousIndex(runs, at, lookup) : -1);
  const prev = $derived(prevAt >= 0 ? { run: runs[prevAt]!, slot: paneSlot(runs[prevAt]!) } : null);
  const clock = $derived(pageClock());

  function refuse(error: unknown): void {
    data.notice = refusalText(error);
  }

  function opened(session: api.CreatedSession, key: string): void {
    openSession(session.id, session.tmux_session ?? null);
    data.notice = t(key);
  }

  function sessionOf(entry: unknown): { id: string | null; tmux: string | null } {
    if (typeof entry === 'string') return { id: entry, tmux: null };
    const e = (entry ?? {}) as Record<string, unknown>;
    const pick = (...keys: string[]): string | null => keys.map((k) => e[k]).find((v): v is string => typeof v === 'string' && v !== '') ?? null;
    return { id: pick('session_id', 'id'), tmux: pick('tmux_session', 'tmux', 'tmux_name') };
  }

  function openSessionsOf(run: PaneRun): void {
    const list = run.sessions ?? [];
    if (list.length === 1) {
      const s = sessionOf(list[0]);
      if (openSession(s.id, s.tmux)) return;
    }
    openSessions();
  }

  async function cancel(run: PaneRun): Promise<void> {
    try {
      await api.cancelRun(run.run_id);
    } catch (error) {
      refuse(error);
    }
    await Promise.all([refresh(), refreshPaneRuns(automation.automation_id)]);
  }

  async function carryOn(run: PaneRun): Promise<void> {
    try {
      opened(await api.continueRun(run.run_id), 'automations.page.toast.continue_opened');
    } catch (error) {
      refuse(error);
    }
  }

  async function fix(runId: string, findingId: string): Promise<void> {
    try {
      opened(await api.fixFinding(runId, findingId), 'automations.page.toast.fix_opened');
    } catch (error) {
      refuse(error);
    }
  }

  function retry(runId: string): void {
    delete reports[runId];
    ensureReport(runId);
  }
</script>

{#if !shown}
  <State data-pane-never-ran title={t('automations.page.pane.never_ran')} hint={t('automations.page.pane.next_run', { when: automation.enabled && automation.next_fire_at ? clock.whenLong(automation.next_fire_at) : t('automations.page.pane.next_none') })}>
    {#snippet glyph()}<Mark status="claimed" size={18} label={t('automations.page.pane.never_ran')} />{/snippet}
    {#snippet actions()}<Button variant="confirm" size="sm" data-act="run" onclick={() => void runNow(automation)}>{t('automations.page.pane.run_now')}</Button>{/snippet}
  </State>
{:else}
  <div class="ap-pn-step" role="group" aria-label={t('automations.page.pane.step_aria')}>
    <Button
      size="sm"
      data-step="1"
      disabled={!older}
      aria-label={older ? t('automations.page.pane.step_older', { n: older.number, status: statusWord(older.status) }) : t('automations.page.pane.step_no_older')}
      onclick={() => onStep(1)}
    >
      <span class="ap-tri" data-d="l" aria-hidden="true"></span>{#if older}<Mark status={older.status} size={10} />{/if}
    </Button>
    <span class="ap-pn-stepn ap-num" aria-live="polite" data-step-n>{t('automations.page.pane.step_of', { n: shown.number, total })}</span>
    {#if at === 0}
      <span class="ap-pn-dim ap-pn-stepw">{t('automations.page.pane.step_newest')}</span>
    {:else}
      <Button variant="quiet" size="sm" data-newest onclick={onNewest}>{t('automations.page.pane.step_newest')}</Button>
    {/if}
    <Button
      size="sm"
      data-step="-1"
      disabled={!newer}
      aria-label={newer ? t('automations.page.pane.step_newer', { n: newer.number, status: statusWord(newer.status) }) : t('automations.page.pane.step_no_newer')}
      onclick={() => onStep(-1)}
    >
      {#if newer}<Mark status={newer.status} size={10} />{/if}<span class="ap-tri" data-d="r" aria-hidden="true"></span>
    </Button>
  </div>
  <RunSheet
    run={shown as unknown as SheetRun}
    slot={paneSlot(shown)}
    composition="pane"
    {clock}
    tz={data.tz}
    now={data.now}
    {prev}
    retryMax={automation.retry_max}
    onRetry={() => retry(shown.run_id)}
    onFix={(runId, findingId) => void fix(runId, findingId)}
    onRunNow={() => void runNow(automation)}
    onContinue={() => void carryOn(shown)}
    onCancel={() => void cancel(shown)}
    onOpenSession={() => openSessionsOf(shown)}
  />
{/if}
