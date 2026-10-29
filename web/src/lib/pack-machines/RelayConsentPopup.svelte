
<script lang="ts">
  import './relay-consent.css';
  import ModalShell from '../launchpad/ModalShell.svelte';
  import { t } from '../i18n/index.svelte';
  import RelayConsentList from './RelayConsentList.svelte';
  import { answerConsent, consentBody, relayConsent, type ConsentAnswer } from './relay-consent-store.svelte';

  const view = $derived(relayConsent.data);
  const pending = $derived((view?.offers ?? []).filter((o) => o.pending));
  const pendingKey = $derived(pending.map((o) => o.key).join('\n'));

  let ticked = $state<string[]>([]);
  let all = $state(true);
  let busy = $state(false);
  let error = $state('');

  $effect(() => {
    void pendingKey;
    ticked = pending.map((o) => o.key);
    all = true;
    error = '';
  });

  async function send(body: ConsentAnswer): Promise<void> {
    if (busy) return;
    busy = true;
    error = '';
    error = await answerConsent(body);
    busy = false;
  }

  function yes(): void {
    const keep = view?.mode === 'list' ? view.accepted : [];
    void send(consentBody(ticked, all, keep));
  }
</script>

{#if pending.length > 0}
  <ModalShell title={t('pack.consent.popup_title')} overlayClass="text-prompt-modal rc-popup" dismissable={false}
    role="alertdialog" describedby="rc-popup-desc" onCancel={() => {}}>
    {#snippet head()}
      <div class="text-prompt-modal__head">
        <span class="text-prompt-modal__verb">&raquo; {t('pack.consent.popup_title')}</span>
      </div>
    {/snippet}
    <p class="rc-desc" id="rc-popup-desc" data-rc="desc">{t('pack.consent.popup_desc')}</p>
    <RelayConsentList offers={pending} bind:ticked bind:all disabled={busy} idBase="rc-popup" />
    {#if error}<p class="rc-error" role="alert" data-rc="error">{error}</p>{/if}
    {#snippet footer()}
      <button type="button" class="modal-btn modal-btn-secondary" data-rc="no" disabled={busy}
        onclick={() => void send({ mode: 'none' })}>{t('pack.consent.no')}</button>
      <button type="button" class="modal-btn modal-btn-confirm" data-rc="yes" disabled={busy || ticked.length === 0}
        onclick={yes}>{t('pack.consent.yes')}</button>
    {/snippet}
  </ModalShell>
{/if}
