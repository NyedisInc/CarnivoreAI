<script lang="ts">
  import '../ledger/ledger-chrome.css';
  import ModalShell from '../launchpad/ModalShell.svelte';
  import { t } from '../i18n/index.svelte';
  import { reviewLines, visibleLines } from './risk';

  let { title, code, onClose, onApprove, onDeny, danger = false, busy = false }: {
    title: string; code: string; onClose: () => void;
    onApprove?: () => void; onDeny?: () => void; danger?: boolean; busy?: boolean;
  } = $props();

  const lines = $derived(reviewLines(code));
  const riskyCount = $derived(lines.filter((line) => line.risks.length > 0).length);
  let riskyOnly = $state(false);
  const shown = $derived(visibleLines(lines, riskyOnly));
  const gutter = $derived(String(lines.length).length);
</script>

<ModalShell title={t('code_review.title')} overlayClass="text-prompt-modal cr-modal" onCancel={onClose}>
  {#snippet head()}
    <div class="text-prompt-modal__head">
      <span class="text-prompt-modal__verb">&raquo; {t('code_review.title')}</span>
      <button type="button" class="modal-close" aria-label={t('code_review.close')} onclick={() => onClose()}>&times;</button>
    </div>
  {/snippet}
  <div class="pledger cr-body" data-code-review>
    <div class="cr-bar">
      <span class="pl-label cr-title" data-code-review-title>{title}</span>
      <span class="pl-label cr-count" data-code-review-count>{t('code_review.count', { risky: riskyCount, total: lines.length })}</span>
      <button type="button" class="modal-btn modal-btn-secondary cr-toggle" aria-pressed={riskyOnly}
        data-code-review-toggle onclick={() => (riskyOnly = !riskyOnly)}>{t('code_review.risky_only')}</button>
    </div>
    <ol class="cr-lines" style:--cr-gutter="{gutter}ch" aria-label={t('code_review.lines_label')} data-code-review-lines>
      {#each shown as line (line.n)}
        <li class="cr-line" class:cr-line--risk={line.risks.length > 0} data-line={line.n}
          data-risk={line.risks.length > 0 ? line.risks.join(' ') : undefined}>
          <span class="cr-num" aria-hidden="true">{line.n}</span>
          <code class="cr-text">{line.text}</code>
          {#each line.risks as risk (risk)}<span class="cr-tag">{t(`code_review.risk.${risk}`)}</span>{/each}
        </li>
      {/each}
    </ol>
    {#if riskyOnly && shown.length === 0}<p class="cr-empty" data-code-review-none>{t('code_review.none_risky')}</p>{/if}
  </div>
  {#snippet footer()}
    <div class="pledger cr-foot">
      {#if onApprove || onDeny}
        <span class="cr-spacer"></span>
        {#if onDeny}<button type="button" class="modal-btn modal-btn-secondary" data-code-review-deny disabled={busy}
          onclick={() => onDeny?.()}>{t('approvals.deny')}</button>{/if}
        {#if onApprove}<button type="button" class="modal-btn {danger ? 'modal-btn-danger' : 'modal-btn-confirm'}" data-code-review-approve disabled={busy}
          onclick={() => onApprove?.()}>{t('approvals.approve')}</button>{/if}
      {:else}
        <span class="cr-spacer"></span>
        <button type="button" class="modal-btn modal-btn-secondary" onclick={() => onClose()}>{t('code_review.close')}</button>
      {/if}
    </div>
  {/snippet}
</ModalShell>

<style>
  :global(.modal-overlay.cr-modal .modal-content) { display: flex; flex-direction: column; max-width: 820px; width: 100%; max-height: 100%; min-height: 0; }
  :global(.modal-overlay.cr-modal .modal-body) { flex: 1 1 auto; min-height: 0; overflow: hidden; padding: 0; margin: 0; }
  :global(.modal-overlay.cr-modal .modal-footer) { padding: 10px 14px; box-shadow: inset 0 1px 0 0 var(--oc-line-rule); }
  @media (max-width: 700px) {
    :global(.modal-overlay.cr-modal) { align-items: stretch; padding: 0; }
    :global(.modal-overlay.cr-modal .modal-content) { max-width: none; border-radius: 0; }
  }
  .cr-body { display: flex; flex-direction: column; min-height: 0; }
  .cr-bar { display: flex; align-items: center; gap: 10px; padding: 8px 14px; box-shadow: inset 0 -1px 0 0 var(--pl-line-quiet); }
  .cr-title { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .cr-count { flex: none; }
  .cr-toggle { flex: none; padding: var(--oc-space-1) 10px; font-size: var(--oc-fs-label); }
  .cr-toggle[aria-pressed='true'] { color: var(--oc-coral); --_bd: var(--oc-coral); border-color: var(--_bd); }
  .cr-lines {
    margin: 0; padding: 0; list-style: none; overflow: auto; overscroll-behavior: contain;
    max-height: min(60vh, 520px); font-family: var(--font-mono); font-size: 12px; line-height: 1.5; color: var(--pl-text);
  }
  .cr-line { display: flex; align-items: baseline; gap: 10px; padding: 0 14px 0 0; box-shadow: inset 2px 0 0 0 transparent; }
  .cr-line--risk {
    background: color-mix(in oklab, var(--oc-coral) 14%, transparent);
    box-shadow: inset 2px 0 0 0 var(--oc-coral);
  }
  .cr-num { flex: none; min-width: calc(var(--cr-gutter, 2ch) + 14px); padding-left: 14px; text-align: right; color: var(--pl-muted); font-variant-numeric: tabular-nums; user-select: none; }
  .cr-text { flex: 1; min-width: 0; font: inherit; white-space: pre-wrap; overflow-wrap: anywhere; }
  .cr-tag { flex: none; color: var(--oc-coral); font-size: var(--oc-fs-micro); letter-spacing: 0.08em; text-transform: uppercase; }
  .cr-empty { margin: 0; padding: 14px; color: var(--pl-muted); font-size: 12px; }
  .cr-foot { display: flex; flex: 1; align-items: center; gap: 8px; min-width: 0; }
  .cr-spacer { flex: 1; }
  .cr-foot :global(.modal-btn:disabled) { opacity: 0.45; cursor: not-allowed; }
</style>
