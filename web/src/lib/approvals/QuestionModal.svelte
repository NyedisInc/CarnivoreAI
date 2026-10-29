<script lang="ts">
  /* nothing waiting permission prompt */
  import { onDestroy, type Snippet } from 'svelte';
  import '../ledger/ledger-chrome.css';
  import ModalShell from '../launchpad/ModalShell.svelte';
  import { t } from '../i18n/index.svelte';
  import { approvals, inboxFocus, noticeKey, refreshApprovals } from './approvals.svelte';
  import ApprovalCard from './ApprovalCard.svelte';
  import AskForm from './AskForm.svelte';
  import { isWholeAsk, oldestFirst, type ApprovalItem } from './approvals-model';

  const SETTLE_MS = 1500;
  const SETTLE_TRIES = 3;
  const SETTLE_RETRY_MS = 600;
  let { onClose, onJump }: { onClose: () => void; onJump: (item: ApprovalItem) => void } = $props();

  const items = $derived(oldestFirst(approvals.items));
  let here = $state<string | null>(null);
  let lastIndex = 0;
  let hadItems = false;
  let spell = 0;
  let spells = 0;
  let destroyed = false;
  onDestroy(() => { destroyed = true; });
  // svelte-ignore state_referenced_locally
  let seenSeq = inboxFocus.seq;

  const index = $derived.by(() => {
    const found = items.findIndex((item) => noticeKey(item) === here);
    if (found >= 0) return found;
    const focused = here === null && inboxFocus.session !== null
      ? items.findIndex((item) => item.session_id === inboxFocus.session) : -1;
    return focused >= 0 ? focused : Math.max(0, Math.min(lastIndex, items.length - 1));
  });
  const current = $derived<ApprovalItem | undefined>(items[index]);

  $effect(() => {
    if (inboxFocus.seq === seenSeq) return;
    seenSeq = inboxFocus.seq;
    const target = items.find((item) => item.session_id === inboxFocus.session);
    if (target) here = noticeKey(target);
  });

  $effect(() => {
    lastIndex = index;
    if (current) here = noticeKey(current);
    if (items.length > 0) {
      hadItems = true;
      spell = 0;
      return undefined;
    }
    if (!hadItems || spell !== 0) return undefined;
    spells += 1;
    spell = spells;
    void settle(spell);
    return undefined;
  });

  const wait = (ms: number): Promise<void> => new Promise((resolve) => setTimeout(resolve, ms));

  async function settle(mine: number): Promise<void> {
    try {
      for (let attempt = 0; attempt < SETTLE_TRIES; attempt += 1) {
        await wait(attempt === 0 ? SETTLE_MS : SETTLE_RETRY_MS);
        if (destroyed || spell !== mine || approvals.items.length > 0) return;
        await refreshApprovals();
        if (destroyed || spell !== mine || approvals.items.length > 0) return;
        if (approvals.status === 'ok') break;
      }
      onClose();
    } finally {
      if (spell === mine) spell = 0;
    }
  }

  let foot = $state.raw<Snippet | null>(null);
  const registerFoot = (next: Snippet | null): void => { foot = next; };

  function step(by: number): void {
    const next = items[index + by];
    if (next) here = noticeKey(next);
  }
</script>

<ModalShell title={t('approvals.title')} overlayClass="ask-modal text-prompt-modal" onCancel={onClose}>
  {#snippet head()}
    <div class="text-prompt-modal__head">
      <span class="text-prompt-modal__verb">&raquo; {t('approvals.title')}</span>
      {#if items.length > 1}
        <div class="pledger aq-pager" data-approval-pager>
          <button type="button" class="modal-btn modal-btn-secondary" disabled={index === 0}
            aria-label={t('approvals.pager.previous')} onclick={() => step(-1)}>&lsaquo;</button>
          <span class="pl-label" data-approval-position>{t('approvals.pager.position', { n: index + 1, total: items.length })}</span>
          <button type="button" class="modal-btn modal-btn-secondary" disabled={index >= items.length - 1}
            aria-label={t('approvals.pager.next')} onclick={() => step(1)}>&rsaquo;</button>
        </div>
      {/if}
      <button type="button" class="modal-close" aria-label={t('approvals.close')}
        onclick={() => onClose()}>&times;</button>
    </div>
  {/snippet}
  <div class="pledger" data-approval-inbox>
    {#if current && isWholeAsk(current)}
      {#key `${noticeKey(current)}|${current.questions_fingerprint}`}<AskForm item={current} {onJump} {registerFoot} />{/key}
    {:else if current}
      {#key current.id}<ApprovalCard item={current} {onJump} strip={false} large {registerFoot} />{/key}
    {:else}
      <p class="aq-empty" data-approval-empty>{approvals.status === 'error' ? t('approvals.load_failed') : t('approvals.empty')}</p>
    {/if}
  </div>
  {#snippet footer()}
    {#if foot}<div class="pledger aq-foot" data-approval-foot>{@render foot()}</div>{/if}
  {/snippet}
</ModalShell>

<style>
  :global(.modal-overlay.ask-modal) { overflow: hidden; padding: var(--oc-space-4); box-sizing: border-box; }
  :global(.modal-overlay.ask-modal .modal-content) {
    display: flex; flex-direction: column; max-width: 760px; max-height: 100%; min-height: 0; margin: auto;
  }
  :global(.modal-overlay.ask-modal .modal-body) { flex: 1 1 auto; min-height: 0; overflow-y: auto; overscroll-behavior: contain; padding: 0; margin: 0; }
  :global(.modal-overlay.ask-modal .modal-footer) {
    padding: 10px 14px max(var(--oc-space-3), env(safe-area-inset-bottom)); box-shadow: inset 0 1px 0 0 var(--oc-line-rule);
  }
  /* nothing waiting */
  :global(.modal-overlay.ask-modal .modal-footer:empty) { display: none; }
  @media (max-width: 700px) {
    :global(.modal-overlay.ask-modal) { align-items: stretch; padding: 0; }
    :global(.modal-overlay.ask-modal .modal-content) { width: 100%; max-width: none; border-radius: 0; margin: 0; }
  }
  .aq-empty { margin: 0; padding: 18px 14px; color: var(--pl-muted); font-size: var(--oc-fs-run-title); }
  .aq-foot { display: flex; flex: 1; min-width: 0; }
  .aq-pager { display: flex; align-items: center; gap: var(--oc-space-2); margin-left: auto; }
  .aq-pager :global(.modal-btn) { padding: 0 10px; font-size: var(--oc-fs-card-name); line-height: 1.4; }
  .aq-pager :global(.modal-btn:disabled) { opacity: 0.45; cursor: not-allowed; }
</style>
