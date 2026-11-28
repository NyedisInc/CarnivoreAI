
<script lang="ts">
  import './relay-consent.css';
  import ModalShell from '../dialog-frame/ModalShell.svelte';
  import { t } from '../i18n/index.svelte';
  import Button from '../base/Button.svelte';
  import { answerApproval, relayApproval } from './relay-approval-store.svelte';
  import { relayConsent } from './relay-consent-store.svelte';

  const consentOpen = $derived((relayConsent.data?.offers ?? []).some((o) => o.pending));
  const next = $derived(consentOpen ? undefined : (relayApproval.data?.computers ?? []).find((c) => c.pending));
  let busy = $state(false);
  let error = $state('');

  async function send(answer: 'yes' | 'no'): Promise<void> {
    if (busy || !next) return;
    busy = true;
    error = await answerApproval(next.install_id, answer);
    busy = false;
  }
</script>

{#if next}
  {@const name = next.label || next.install_id.slice(0, 8)}
  <ModalShell title={t('pack.approval.title', { computer: name })} overlayClass="text-prompt-modal rc-popup" dismissable={false}
    role="alertdialog" describedby="ra-popup-desc" onCancel={() => {}}>
    {#snippet head()}
      <div class="text-prompt-modal__head">
        <span class="text-prompt-modal__verb">&raquo; {t('pack.approval.title', { computer: name })}</span>
      </div>
    {/snippet}
    <p class="rc-desc" id="ra-popup-desc" data-ra="desc">{t(relayApproval.data?.covers_pack ? 'pack.approval.desc_pack' : 'pack.approval.desc')}</p>
    {#if error}<p class="rc-error" role="alert" data-ra="error">{error}</p>{/if}
    {#snippet footer()}
      <Button data-ra="no" disabled={busy} onclick={() => void send('no')}>{t('pack.consent.no')}</Button>
      <Button variant="confirm" data-ra="yes" disabled={busy} onclick={() => void send('yes')}>{t('pack.consent.yes')}</Button>
    {/snippet}
  </ModalShell>
{/if}
