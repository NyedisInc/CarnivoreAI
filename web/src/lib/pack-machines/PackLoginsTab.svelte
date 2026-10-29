<script lang="ts">
  import '../ledger/ledger-chrome.css';
  import './pack-machines.css';
  import './pack-settings.css';
  import { t } from '../i18n/index.svelte';
  import Check from '../../opscenter/ui/Check.svelte';
  import PackRelayBlock from './PackRelayBlock.svelte';
  import PackReceiveConsent from './PackReceiveConsent.svelte';
  import { packActivity, packMachines, saveRestrictions } from './pack-machines-store.svelte';

  const self = $derived(packMachines.data?.machines.find((m) => m.is_self));
  const receives = $derived(self?.snapshot?.restrictions.may_receive_credentials === true);
</script>

<section class="pm-panel pl-panel pledger" aria-labelledby="pl-logins-title" data-pack-logins>
  <div class="pl-titlebar">
    <h2 class="pl-title" id="pl-logins-title">{t('pack.logins.title')}</h2>
  </div>
  <div class="pm-body pk-col">
    {#if packActivity.error}<p class="pm-error" role="alert" data-pm="error">{packActivity.error}</p>{/if}
    <PackRelayBlock />
    {#if self?.snapshot}
      <div class="pm-settings" data-pm="receive-logins">
        <h3 class="pl-label">{t('pack.logins.receive_title')}</h3>
        <Check label={t('pack.machines.rule.may_receive_credentials')} hint={t('pack.logins.receive_help')} checked={receives} role="switch"
          disabled={packActivity.busy !== null} data-rule="may_receive_credentials"
          onToggle={(next) => void saveRestrictions(self.install_id, { may_receive_credentials: next })} />
      </div>
    {/if}
    <PackReceiveConsent />
  </div>
</section>
