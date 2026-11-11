<script lang="ts">
  import './pack-machines.css';
  import { t } from '../i18n/index.svelte';
  import Check from '../../opscenter/ui/Check.svelte';
  import { packMachines } from './pack-machines-store.svelte';
  import { answerApproval, relayApproval } from './relay-approval-store.svelte';
  import { claudeAccounts, packRelay, relayActivity, setRelay } from './pack-relay-store.svelte';

  const accounts = $derived(claudeAccounts.data ?? []);
  const targets = $derived(packRelay.data?.accounts ?? {});
  const peers = $derived((packMachines.data?.machines ?? []).filter((m) => !m.is_self && m.paired));

  const approvals = $derived((relayApproval.data?.computers ?? []).filter((c) => !c.pending));

  function nameOf(id: string): string {
    const found = packMachines.data?.machines.find((m) => m.install_id === id);
    return found?.label || id.slice(0, 8);
  }
</script>

{#if accounts.length > 0}
  <div class="pm-relay" data-pm="relay">
    {#each approvals as c (c.install_id)}
      <div class="pm-relay-row" data-relay-approval={c.install_id}>
        <Check label={t('pack.approval.row', { computer: c.label || c.install_id.slice(0, 8) })} checked={c.answer === 'yes'} role="switch"
          data-relay="approval" onToggle={(next) => void answerApproval(c.install_id, next ? 'yes' : 'no')} />
      </div>
    {/each}
    <h3 class="oc-label">{t('pack.machines.relay_title')}</h3>
    <p class="pm-note">{t('pack.machines.relay_help')}</p>
    {#if relayActivity.error}<p class="pm-error" role="alert" data-pm="relay-error">{relayActivity.error}</p>{/if}
    {#each accounts as account (account.id)}
      {@const rows = targets[account.id] ?? []}
      <div class="pm-relay-row" data-relay-account={account.id}>
        <Check label={account.name || account.id} checked={rows.length > 0} role="switch"
          disabled={relayActivity.busy !== null || (rows.length === 0 && peers.length === 0)} data-relay="toggle"
          onToggle={(next) => void setRelay(account.id, next ? peers.map((m) => m.install_id) : [])} />
        {#each rows as row (row.machine)}
          <span class="pm-state" data-relay="state">{nameOf(row.machine)}: {row.state}</span>
        {/each}
      </div>
    {/each}
  </div>
{/if}
