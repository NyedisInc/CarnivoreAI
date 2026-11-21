
<script lang="ts">
  import { onMount } from 'svelte';
  import { t } from '../i18n/index.svelte';
  import { stateWords } from './ssh-state-words';
  import { sshTargetsApi, type SshTargetsApi } from './ssh-targets-api';
  import { loadSshTargets, sshTargets } from './ssh-targets-store.svelte';

  const { api = sshTargetsApi }: { api?: SshTargetsApi } = $props();
  onMount(() => { void loadSshTargets(api); });
</script>

{#if sshTargets.list.length > 0}
  <div data-ad="ssh-rows">
    <h4 class="oc-label">{t('pack.ssh.rows.title')}</h4>
    <ul class="pt-replica-list">
      {#each sshTargets.list as target (target.host_key)}
        <li class="pt-replica" data-ssh-row={target.host_key}>
          <div><p class="modal-description">{target.label}</p><p class="pt-note" data-ssh="row-state">{stateWords(target, sshTargets.changed[target.host_key] === true)}</p></div>
        </li>
      {/each}
    </ul>
  </div>
{/if}
