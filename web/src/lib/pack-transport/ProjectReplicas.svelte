<script lang="ts">
  /* run the project */
  import { t } from '../i18n/index.svelte';
  import { nonEmptyErrorMessageOr } from '../errors/failure-reason';
  import Button from '../base/Button.svelte';
  import IconButton from '../base/IconButton.svelte';
  import List from '../base/List.svelte';
  import ListRow from '../base/ListRow.svelte';
  import Select from '../base/Select.svelte';
  import State from '../base/State.svelte';
  import InfoTip from '../info-tip/InfoTip.svelte';
  import { projects } from '../../opscenter/api/projects.svelte';
  import { packMachines } from '../pack-machines/pack-machines-store.svelte';
  import ComputerGlyph from './ComputerGlyph.svelte';
  import { replicasApi, type ReplicasApi, type ReplicasView } from './transport-api';

  let { name, projectName = '', api = replicasApi, onchange }: { name: string; projectName?: string; api?: ReplicasApi; onchange?: () => void } = $props();

  let view = $state<ReplicasView | null>(null);
  let pick = $state('');
  let armed = $state<string | null>(null);
  let busy = $state(false);
  let error = $state<string | null>(null);

  const machines = $derived(packMachines.data?.machines ?? []);
  const targets = $derived(machines.filter((m) => m.paired && !m.is_self && m.state === 'connected' && !(view?.replicas ?? []).some((r) => r.install_id === m.install_id)));
  const online = (installId: string): boolean => machines.find((m) => m.install_id === installId)?.state === 'connected';

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
      onchange?.();
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

  let seen: number | null | undefined;
  $effect(() => {
    const stamp = projects.fetchedAt;
    if (seen === undefined) { seen = stamp; return; }
    if (stamp !== seen) { seen = stamp; void load(); }
  });
</script>

<div class="dk-pagebody" data-pt="replicas">
  <h4 class="oc-sub">{t('pack.replicas.title')} <InfoTip text={t('pack.replicas.help')} label={t('pack.transport.info_label')} /></h4>
  <div class="dk-desc"><p>{t('pack.deck.rep_one')}</p></div>
  {#if error}<State kind="error" inline title={error} data-pt="replicas-error" />{/if}
  {#if view}
    {#if view.replicas.length === 0}
      <State kind="empty" inline title={t('pack.replicas.none')} data-pt="replicas-none" />
    {:else}
      <List label={t('pack.replicas.title')}>
        {#each view.replicas as replica (replica.install_id)}
          <ListRow class="dk-rep" data-replica={replica.install_id} primary={replica.label} secondary={t('pack.deck.rep_row', { project: projectName })}>
            {#snippet lead()}<ComputerGlyph kind={online(replica.install_id) ? 'linked' : 'down'} />{/snippet}
            {#snippet actions()}
              {#if armed === replica.install_id}
                <Button variant="danger" size="sm" disabled={busy} data-pt="replica-remove" onclick={() => remove(replica.install_id)}>{t('pack.replicas.remove_confirm')}</Button>
              {:else}
                <IconButton icon="trash" iconSize={14} variant="danger" label={t('pack.replicas.remove_aria', { computer: replica.label })} disabled={busy} data-pt="replica-remove"
                  onclick={() => remove(replica.install_id)} />
              {/if}
            {/snippet}
          </ListRow>
        {/each}
      </List>
    {/if}
    {#if view.pack_state === 'home'}
      {#if targets.length === 0}
        <State kind="empty" inline title={t('pack.replicas.no_target')} data-pt="replicas-no-target" />
      {:else}
        <div class="dk-fieldrow">
          <Select bind:value={pick} size="sm" aria-label={t('pack.replicas.pick')} disabled={busy} data-pt="replica-pick">
            <option value="">{t('pack.replicas.pick')}</option>
            {#each targets as machine (machine.install_id)}<option value={machine.install_id}>{machine.label || machine.install_id.slice(0, 8)}</option>{/each}
          </Select>
          <Button variant="confirm" disabled={busy || !pick} data-pt="replica-add" onclick={() => void change(() => api.add(name, pick))}>{t('pack.replicas.add')}</Button>
        </div>
      {/if}
    {/if}
  {/if}
</div>
