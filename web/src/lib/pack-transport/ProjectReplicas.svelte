<script lang="ts">
  import { t } from '../i18n/index.svelte';
  import { nonEmptyErrorMessageOr } from '../errors/failure-reason';
  import { packMachines } from '../pack-machines/pack-machines-store.svelte';
  import { replicasApi, type ReplicasApi, type ReplicasView } from './transport-api';

  let { name, api = replicasApi }: { name: string; api?: ReplicasApi } = $props();

  let view = $state<ReplicasView | null>(null);
  let pick = $state('');
  let armed = $state<string | null>(null);
  let busy = $state(false);
  let error = $state<string | null>(null);

  const targets = $derived(
    (packMachines.data?.machines ?? []).filter(
      (m) => m.paired && !m.is_self && m.state === 'connected' && !(view?.replicas ?? []).some((r) => r.install_id === m.install_id),
    ),
  );

  async function load(): Promise<void> {
    try {
      view = await api.list(name);
    } catch (failure) {
      error = nonEmptyErrorMessageOr(failure, t('pack.replicas.error.failed'));
    }
  }

  async function change(send: () => Promise<unknown>): Promise<void> {
    if (busy) return;
    busy = true;
    error = null;
    try {
      await send();
      pick = '';
      armed = null;
    } catch (failure) {
      error = nonEmptyErrorMessageOr(failure, t('pack.replicas.error.failed'));
    } finally {
      busy = false;
      await load();
    }
  }

  function remove(installId: string): void {
    if (armed !== installId) {
      armed = installId;
      return;
    }
    void change(() => api.remove(name, installId));
  }

  void load();
</script>

<div class="pt-replicas" data-pt="replicas">
  <h4 class="oc-label">{t('pack.replicas.title')}</h4>
  {#if error}<p class="pt-error" role="alert" data-pt="replicas-error">{error}</p>{/if}
  {#if view}
    <p class="pt-note">{t('pack.replicas.help')}</p>
    {#if view.replicas.length === 0}
      <p class="pt-note" data-pt="replicas-none">{t('pack.replicas.none')}</p>
    {:else}
      <ul class="pt-replica-list">
        {#each view.replicas as replica (replica.install_id)}
          <li class="pt-replica" data-replica={replica.install_id}>
            <span class="pt-line">{replica.label}</span>
            <button type="button" class="modal-btn modal-btn-danger" disabled={busy} data-pt="replica-remove"
              onclick={() => remove(replica.install_id)}>{armed === replica.install_id ? t('pack.replicas.remove_confirm') : t('pack.replicas.remove')}</button>
          </li>
        {/each}
      </ul>
    {/if}
    {#if view.pack_state === 'home'}
      {#if targets.length === 0}
        <p class="pt-note" data-pt="replicas-no-target">{t('pack.replicas.no_target')}</p>
      {:else}
        <div class="pt-row">
          <select class="oc-field" bind:value={pick} aria-label={t('pack.replicas.pick')} disabled={busy} data-pt="replica-pick">
            <option value="">{t('pack.replicas.pick')}</option>
            {#each targets as machine (machine.install_id)}<option value={machine.install_id}>{machine.label || machine.install_id.slice(0, 8)}</option>{/each}
          </select>
          <button type="button" class="modal-btn modal-btn-confirm" disabled={busy || !pick} data-pt="replica-add"
            onclick={() => void change(() => api.add(name, pick))}>{t('pack.replicas.add')}</button>
        </div>
      {/if}
    {/if}
  {/if}
</div>
