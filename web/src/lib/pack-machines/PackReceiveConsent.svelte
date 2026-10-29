
<script lang="ts">
  import './pack-machines.css';
  import './relay-consent.css';
  import { t } from '../i18n/index.svelte';
  import RelayConsentList from './RelayConsentList.svelte';
  import { answerConsent, consentBody, relayConsent } from './relay-consent-store.svelte';

  const view = $derived(relayConsent.data);
  const offers = $derived(view?.offers ?? []);
  const serverTicked = $derived(offers.filter((o) => o.accepted).map((o) => o.key));
  const serverAll = $derived(view?.mode === 'all');
  const serverSig = $derived(`${view?.mode ?? ''}|${serverTicked.join(',')}|${offers.map((o) => o.key).join(',')}`);

  let ticked = $state<string[]>([]);
  let all = $state(false);
  let dirty = $state(false);
  let busy = $state(false);
  let error = $state('');

  $effect(() => {
    void serverSig;
    if (dirty) return;
    ticked = [...serverTicked];
    all = serverAll;
  });

  async function save(): Promise<void> {
    if (busy) return;
    busy = true;
    error = await answerConsent(consentBody(ticked, all));
    if (!error) dirty = false;
    busy = false;
  }
</script>

{#if view && offers.length > 0}
  <div class="pm-settings" data-pm="receive-consent">
    <h3 class="pl-label">{t('pack.consent.receive_title')}</h3>
    <p class="pm-note">{t('pack.consent.receive_help')}</p>
    <RelayConsentList {offers} bind:ticked bind:all disabled={busy} idBase="rc-logins" onedit={() => (dirty = true)} />
    {#if error}<p class="pm-error" role="alert" data-rc="error">{error}</p>{/if}
    <div class="rc-actions">
      <button type="button" class="modal-btn modal-btn-confirm" data-rc="save" disabled={busy || !dirty} onclick={() => void save()}>
        {t('pack.consent.save')}</button>
    </div>
  </div>
{/if}
