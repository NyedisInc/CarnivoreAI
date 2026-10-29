<script lang="ts">
  /* permission prompt */
  import { t } from '../i18n/index.svelte';
  import CodeReviewModal from '../code-review/CodeReviewModal.svelte';
  import { itemCode } from '../code-review/risk';
  import { answerDialog, decideAgentAction } from './approvals.svelte';
  import { canApprove, type ApprovalItem } from './approvals-model';

  let { item, title = '' }: { item: ApprovalItem; title?: string } = $props();

  const code = $derived(itemCode(item));
  const dialogAnswer = $derived(item.source === 'dialog' && canApprove(item));
  const agentAnswer = $derived(item.source === 'agent_action' && !item.confirm_text);
  const answerable = $derived(dialogAnswer || agentAnswer);
  const danger = $derived(item.display?.tone === 'danger');
  let open = $state(false);
  let busy = $state(false);

  async function answer(run: () => Promise<boolean>): Promise<void> {
    if (busy) return;
    busy = true;
    try {
      if (await run()) open = false;
    } finally {
      busy = false;
    }
  }

  function toBody(node: HTMLElement): { destroy: () => void } {
    document.body.appendChild(node);
    return { destroy: () => node.remove() };
  }

  const approve = (): Promise<void> => answer(() => (dialogAnswer ? answerDialog(item, { plain: 'yes' }) : decideAgentAction(item, true)));
  const deny = (): Promise<void> => answer(() => (dialogAnswer ? answerDialog(item, { plain: 'no' }) : decideAgentAction(item, false)));
</script>

{#if code !== null}
  <button type="button" class="modal-btn modal-btn-secondary ar-open" data-approval-open aria-label={t('code_review.open_label')}
    onclick={() => (open = true)}>{t('code_review.open')}</button>
  {#if open}
    <div class="ar-host" use:toBody>
    <CodeReviewModal title={title || item.summary || item.question || ''} {code} {danger} {busy} onClose={() => (open = false)}
      onApprove={answerable ? () => void approve() : undefined} onDeny={answerable ? () => void deny() : undefined} />
    </div>
  {/if}
{/if}

<style>
    @layer components {
      .ar-open { flex: none; }

      .ar-host { display: contents; }
    }
</style>
