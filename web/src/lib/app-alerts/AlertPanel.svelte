<script lang="ts">
  import AnchoredPopup from '../dialog-frame/AnchoredPopup.svelte';
  import '../ledger/ledger-chrome.css';
  import { t } from '../i18n/index.svelte';
  import Glyph from '../Glyph.svelte';
  import { alertCenter, dismissAlert, dismissResolvedAlerts, refreshAlerts, runAlertAction, snoozeAlert } from './alerts.svelte';
  import { kindOf, panelSections, primaryAction, senderText, type AlertAction, type AppAlert } from './alerts-model';
  import ApprovalReview from '../approvals/ApprovalReview.svelte';
  import { approvals } from '../approvals/approvals.svelte';
  import Icon from '../../opscenter/ui/Icon.svelte';
  import { attentionKinds } from '../attention-kinds/kinds';
  import { openAttention } from '../attention-kinds/open';
  import { bellRows, startAttentionSources } from '../attention-kinds/read.svelte';
  import type { AttentionRow } from '../attention-kinds/rows';

  let { onClose }: { onClose: () => void } = $props();

  const SNOOZE_MINUTES = 60;

  $effect(() => startAttentionSources());

  const waiting = $derived(bellRows().filter((row) => row.source !== 'alert'));
  const kindList = $derived(attentionKinds(alertCenter.sources));
  const sections = $derived(panelSections(alertCenter.alerts));
  let openFailed = $state('');
  let showResolved = $state(false);
  let busy = $state(false);
  let explaining = $state<Record<number, boolean>>({});
  let notes = $state<Record<number, string>>({});

  function when(stamp: string | null): string {
    if (!stamp) return '';
    const date = new Date(stamp);
    return Number.isNaN(date.getTime()) ? '' : date.toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
  }

  async function act(run: () => Promise<unknown>): Promise<void> {
    if (busy) return;
    busy = true;
    try {
      await run();
    } catch {
    } finally {
      busy = false;
    }
  }

  async function runAction(alert: AppAlert, action: AlertAction): Promise<void> {
    notes[alert.id] = action.id === 'recheck' ? t('app_alert.row.rechecking') : '';
    try {
      await runAlertAction(action);
      notes[alert.id] = action.id === 'recheck' ? t('app_alert.row.rechecked') : '';
    } catch {
      notes[alert.id] = t('app_alert.row.recheck_failed');
    }
    await refreshAlerts();
  }

  function toggleExplain(alert: AppAlert): void {
    explaining[alert.id] = !explaining[alert.id];
  }

  async function openRow(row: AttentionRow): Promise<void> {
    const outcome = await openAttention(row.target);
    openFailed = outcome.failedKey ? t(outcome.failedKey) : outcome.failedText;
    if (!openFailed && row.source !== 'alert') onClose();
  }
</script>


<AnchoredPopup class="pledger aa-panel" label={t('app_alert.panel.title')} data-app-alert-panel="" placement="manual"
  initialFocus="none" escape="window" outside="none" {onClose}>
  <div class="pl-titlebar">
    <h2 class="pl-title">{t('app_alert.panel.title')}</h2>
    <span class="aa-spacer"></span>
    <button type="button" class="aa-close" aria-label={t('app_alert.panel.close')}
      onclick={() => onClose()}>
      <svg viewBox="0 0 16 16" aria-hidden="true"><path d="M4 4l8 8M12 4l-8 8" /></svg>
    </button>
  </div>

  <div class="aa-body">
    {#if alertCenter.status === 'error' && alertCenter.alerts.length === 0}
      <p class="aa-empty">{t('app_alert.panel.load_failed')}</p>
    {:else if sections.open.length === 0 && waiting.length === 0}
      <p class="aa-empty">{t('app_alert.panel.empty')}</p>
    {/if}

    {#each waiting as row (row.key)}
      {@const kind = kindList.find((k) => k.id === row.kindId)}
      {@const review = row.source === 'approval' ? approvals.items.find((i) => `approval:${i.id}` === row.key) : undefined}
      <div class="aa-wait-wrap">
      <button type="button" class="aa-row aa-wait" data-bell-row={row.key} data-bell-kind={row.kindId} onclick={() => void openRow(row)}>
        <span class="aa-mark aa-mark--{row.severity}"></span>
        <span class="aa-text">
          <span class="aa-meta">
            <span class="aa-source pl-label"><span class="aa-source-glyph"><Icon name={kind?.icon ?? 'bell'} size={12} /></span><span>{kind ? t(kind.labelKey) : row.kindId}</span></span>
          </span>
          <span class="aa-title">{row.what}</span>
          {#if row.where}<span class="aa-detail">{row.where}</span>{/if}
        </span>
      </button>
      {#if review}<div class="aa-wait-open" data-bell-open-row={row.key}><ApprovalReview item={review} title={row.what} /></div>{/if}
      </div>
    {/each}
    {#if openFailed}<p class="aa-empty" role="status" data-bell-open-failed>{openFailed}</p>{/if}

    {#each sections.open as alert (alert.id)}
      {@const kind = kindOf(alert)}
      {@const primary = primaryAction(alert)}
      <div class="aa-row" data-app-alert-row={alert.id} data-severity={alert.severity} data-kind={kind}>
        <span class="aa-mark aa-mark--{alert.severity}" aria-label={t(`app_alert.severity.${alert.severity}`)}></span>
        <div class="aa-text">
          <div class="aa-meta">
            <span class="aa-source pl-label" data-app-alert-source>
              {#if alert.source_icon}<span class="aa-source-glyph"><Glyph name={alert.source_icon} size={12} /></span>{/if}
              <span>{senderText(alert, t)}</span>
            </span>
            <span class="aa-chip aa-chip--{kind}" data-app-alert-kind={kind}>{t(`app_alert.kind.${kind}`)}</span>
          </div>
          <div class="aa-title">{t(alert.title_key, alert.params)}{#if alert.count > 1}<span class="aa-count">{t('app_alert.row.count', { count: alert.count })}</span>{/if}</div>
          {#if alert.detail_key}<div class="aa-detail">{t(alert.detail_key, alert.params)}</div>{/if}
          {#each alert.actions as action (action.id)}
            {#if action.explain_key && explaining[alert.id]}
              <div class="aa-explain" data-app-alert-explain={action.id}>
                <p class="aa-explain-text">{t(action.explain_key, alert.params)}</p>
                <div class="aa-actions">
                  {#each action.actions ?? [] as inner, i (inner.id)}
                    <button type="button" class="modal-btn {inner.tone === 'danger' ? 'modal-btn-danger' : i === 0 ? 'modal-btn-confirm' : 'modal-btn-secondary'}" disabled={busy}
                      data-app-alert-action={inner.id} onclick={() => act(() => runAction(alert, inner))}>{t(inner.label_key)}</button>
                  {/each}
                  <button type="button" class="modal-btn modal-btn-secondary" onclick={() => toggleExplain(alert)}>{t('app_alert.row.explain_hide')}</button>
                </div>
              </div>
            {/if}
          {/each}
          <div class="pl-label">
            {t('app_alert.row.seen', { first: when(alert.first_seen), last: when(alert.last_seen) })}
            {#if alert.state === 'snoozed'}{t('opscenter.list.separator')}{t('app_alert.row.snoozed')}{/if}
            {#if notes[alert.id]}{t('opscenter.list.separator')}{notes[alert.id]}{/if}
          </div>
          <div class="aa-actions">
            {#each alert.actions as action (action.id)}
              {@const tone = action.tone === 'danger' ? 'modal-btn-danger' : action === primary ? 'modal-btn-confirm' : 'modal-btn-secondary'}
              {#if action.explain_key}
                <button type="button" class="modal-btn {tone}" aria-expanded={!!explaining[alert.id]} disabled={busy}
                  data-app-alert-action={action.id} onclick={() => toggleExplain(alert)}>{t(action.label_key)}</button>
              {:else if action.href}
                <a class="modal-btn {tone}" href={action.href} data-app-alert-action={action.id} onclick={() => onClose()}>{t(action.label_key)}</a>
              {:else}
                <button type="button" class="modal-btn {tone}" disabled={busy}
                  data-app-alert-action={action.id} onclick={() => act(() => runAction(alert, action))}>{t(action.label_key)}</button>
              {/if}
            {/each}
            {#if alert.state === 'active'}
              <button type="button" class="modal-btn modal-btn-secondary" disabled={busy}
                onclick={() => act(() => snoozeAlert(alert.id, SNOOZE_MINUTES))}>{t('app_alert.row.snooze')}</button>
            {/if}
            <button type="button" class="modal-btn modal-btn-secondary" disabled={busy}
              onclick={() => act(() => dismissAlert(alert.id))}>{t('app_alert.row.dismiss')}</button>
          </div>
        </div>
      </div>
    {/each}

    {#if sections.resolved.length > 0}
      <div class="aa-fold">
        <button type="button" class="oc-btn pl-label" aria-expanded={showResolved}
          onclick={() => (showResolved = !showResolved)}>{t('app_alert.panel.resolved', { count: sections.resolved.length })}</button>
        <span class="aa-spacer"></span>
        <button type="button" class="modal-btn modal-btn-secondary" disabled={busy}
          onclick={() => act(() => dismissResolvedAlerts())}>{t('app_alert.panel.dismiss_resolved')}</button>
      </div>
      {#if showResolved}
        {#each sections.resolved as alert (alert.id)}
          <div class="aa-row aa-row--resolved" data-app-alert-row={alert.id}>
            <span class="aa-mark aa-mark--resolved"></span>
            <div class="aa-text">
              <div class="aa-title">{t(alert.title_key, alert.params)}</div>
              <div class="pl-label">{t('app_alert.row.resolved_at', { time: when(alert.resolved_at) })}</div>
            </div>
          </div>
        {/each}
      {/if}
    {/if}
  </div>
</AnchoredPopup>

<style>
  :global(.aa-panel) {
    position: fixed;
    top: 56px;
    right: 12px;
    z-index: 1200;
    width: min(460px, calc(100vw - 24px));
    max-height: min(70vh, 640px);
    display: flex;
    flex-direction: column;
    font-family: var(--font-mono);
    color: var(--pl-text);
    border-radius: var(--pl-radius-sm);
  }
  .aa-spacer { flex: 1; }
  .aa-close {
    width: 24px;
    height: 24px;
    padding: 4px;
    background: transparent;
    border: var(--oc-border, 1px) solid transparent;
    border-radius: var(--pl-radius-sm);
    color: var(--pl-muted);
    cursor: pointer;
  }
  .aa-close:hover { color: var(--pl-text); border-color: var(--pl-line); }
  .aa-close svg { width: 100%; height: 100%; fill: none; stroke: currentColor; stroke-width: 1.5; stroke-linecap: round; }
  .aa-body { overflow-y: auto; min-height: 0; }
  .aa-empty { margin: 0; padding: 14px 12px; color: var(--pl-muted); font-size: 12px; }
  .aa-row {
    display: flex;
    gap: 10px;
    align-items: flex-start;
    padding: 10px 12px;
    box-shadow: inset 0 -1px 0 0 var(--pl-line-quiet);
  }
  .aa-row--resolved { opacity: 0.7; }
  .aa-wait { width: 100%; border: 0; background: transparent; color: inherit; font: inherit; text-align: left; cursor: pointer; }
  .aa-wait-wrap { box-shadow: inset 0 -1px 0 0 var(--pl-line-quiet); }
  .aa-wait-wrap .aa-wait { box-shadow: none; }
  .aa-wait-open { display: flex; padding: 0 12px 8px; }
  .aa-wait:hover { background: var(--oc-ground-hover); }
  .aa-mark {
    flex: none;
    width: 8px;
    height: 8px;
    margin-top: 4px;
    border-radius: 1px;
    background: var(--pl-dim);
  }
  .aa-mark--error { background: var(--oc-coral); }
  .aa-mark--warn { background: var(--oc-yellow); }
  .aa-mark--info { background: var(--oc-cyan); }
  .aa-mark--resolved { background: var(--oc-green); }
  .aa-text { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 3px; }
  .aa-title { font-size: 12px; color: var(--pl-text); }
  .aa-count { margin-left: 6px; color: var(--pl-muted); }
  .aa-detail { font-size: 11px; color: var(--pl-muted); }
  .aa-actions { display: flex; flex-wrap: wrap; gap: 6px; padding-top: 4px; }
  .aa-meta { display: flex; align-items: center; gap: 8px; justify-content: space-between; min-width: 0; }
  .aa-source { display: inline-flex; align-items: center; gap: 5px; min-width: 0; text-transform: uppercase; letter-spacing: 0.08em; }
  .aa-source-glyph { display: inline-flex; flex: none; color: var(--pl-muted); }
  .aa-chip {
    flex: none;
    padding: 1px 6px;
    border: var(--oc-border, 1px) solid var(--pl-line);
    border-radius: var(--pl-radius-sm);
    font-size: var(--oc-fs-label);
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: var(--pl-muted);
  }
  .aa-chip--needs_you {
    color: var(--oc-orange-bright);
    border-color: var(--oc-orange);
    background: color-mix(in oklab, var(--oc-orange) 18%, transparent);
  }
  .aa-chip--question { color: var(--oc-cyan); border-color: var(--oc-cyan); }
  .aa-explain { margin: 4px 0; padding: 8px 0; box-shadow: inset 0 1px 0 0 var(--pl-line-quiet), inset 0 -1px 0 0 var(--pl-line-quiet); }
  .aa-explain-text { margin: 0; font-size: 11px; color: var(--pl-text); line-height: 1.5; }
  .aa-actions .modal-btn,
  .aa-fold .modal-btn { padding: var(--oc-space-1) 10px; font-size: var(--oc-fs-label); }
  .aa-actions a.modal-btn { display: inline-flex; align-items: center; text-decoration: none; }
  .aa-actions .modal-btn:disabled,
  .aa-fold .modal-btn:disabled { opacity: 0.45; cursor: not-allowed; }
  .aa-fold {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 8px 12px;
    box-shadow: inset 0 -1px 0 0 var(--pl-line-quiet);
  }
</style>
