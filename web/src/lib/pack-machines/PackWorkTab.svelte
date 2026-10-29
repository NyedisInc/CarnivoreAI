<script lang="ts">
  import '../ledger/ledger-chrome.css';
  import './pack-machines.css';
  import './pack-settings.css';
  import './pack-work.css';
  import { t } from '../i18n/index.svelte';
  import Check from '../../opscenter/ui/Check.svelte';
  import PackSettingsBlock from './PackSettingsBlock.svelte';
  import PackReserveRow from './PackReserveRow.svelte';
  import PackMarks from './PackMarks.svelte';
  import MigrateWizard from '../pack-migrate/MigrateWizard.svelte';
  import { migrate, openMigrate, planMove } from '../pack-migrate/migrate-store.svelte';
  import { projects } from '../../opscenter/api/projects.svelte';
  import { companyList } from '../companies';
  import { sessions } from '../../opscenter/api/sessions.svelte';
  import { moveGroups } from './move-options';
  import { packActivity, packMachines, setTracksMaster, tracksMaster, type PackMachine } from './pack-machines-store.svelte';

  const view = $derived(packMachines.data);
  const alpha = $derived(view?.machines.find((m) => m.is_master));
  const movable = $derived((projects.data ?? []).filter((p) => !p.archived_at && (p.pack_state ?? 'home') === 'home'));
  let moveKey = $state('');
  const groups = $derived(moveGroups(companyList(), movable, sessions.data ?? []));
  const online = $derived((view?.machines ?? []).filter((m) => m.state === 'connected' || m.state === 'self').length);
  const peers = $derived((view?.machines ?? []).filter((m) => !m.is_self && m.paired));
  let targetId = $state('');

  const refuses = (m: PackMachine): boolean => m.state !== 'connected' || m.snapshot?.restrictions.may_receive_projects !== true;

  function startMove(): void {
    const machine = peers.find((m) => m.install_id === targetId);
    if (!moveKey || !machine) return;
    openMigrate({ kind: moveKey.startsWith('c:') ? 'company' : 'project', name: moveKey.slice(2) });
    void planMove(machine.label || machine.install_id);
  }
</script>

<section class="pm-panel pl-panel pledger" aria-labelledby="pw-title" data-pack-work>
  <div class="pl-titlebar">
    <h2 class="pl-title" id="pw-title">{t('pack.work.title')}</h2>
  </div>
  <div class="pw-body">
    {#if view?.disagreement}
      <p class="pm-warn" role="status" data-pm="disagreement">{t('pack.machines.disagreement', { machines: view.disagreement.join(', ') })}</p>
    {/if}
    {#if packActivity.error}<p class="pm-error" role="alert" data-pm="error">{packActivity.error}</p>{/if}
    {#if !view}
      <p class="pm-note">{t('pack.machines.loading')}</p>
    {:else}
      <div class="pw-strip" data-pw="strip">
        <span data-pm="master-line"><span class="pl-label">{t('pack.machines.master')}</span>
          <span class="pm-name">{alpha ? alpha.label || alpha.install_id.slice(0, 8) : t('pack.machines.no_master')}</span></span>
        <span data-pw="count">{t('pack.work.strip.computers', { n: view.machines.filter((m) => m.paired || m.is_self).length, online })}</span>
        {#if tracksMaster.data}
          <span data-pw="follows">{t(tracksMaster.data.tracks_master ? 'pack.work.strip.follows' : 'pack.work.strip.not_follows')}</span>
        {/if}
      </div>
      {#if tracksMaster.data}
        <div>
          <Check label={t('pack.machines.tracks_master')} hint={t('pack.machines.tracks_master_help')} checked={tracksMaster.data.tracks_master}
            role="switch" disabled={packActivity.busy !== null} data-pm="tracks-master" onToggle={(next) => void setTracksMaster(next)} />
          <details class="pw-more"><summary class="pm-note">{t('pack.work.more')}</summary><p class="pm-note">{t('pack.work.follow_more')}</p></details>
        </div>
      {/if}
      <div class="pw-grid">
        <PackSettingsBlock />
        <div class="pm-settings pw-group" data-pm="machine-rules">
          <h3 class="pl-label">{t('pack.work.per_computer')}</h3>
          <ul class="pm-list">
            {#each view.machines.filter((m) => m.paired && m.snapshot) as machine (machine.install_id)}
              <PackReserveRow {machine} />
            {/each}
          </ul>
        </div>
      </div>
      <div class="pm-settings" data-pm="migrate">
        <h3 class="pl-label">{t('pack.migrate.panel_title')}</h3>
        <div class="pw-move">
          <select class="pk-field pk-select" bind:value={moveKey} aria-label={t('pack.migrate.panel_pick')} data-pm="migrate-pick">
            <option value="">{t('pack.migrate.panel_pick')}</option>
            {#each [['pack.migrate.group.active', groups.active], ['pack.migrate.group.others', groups.others]] as const as [label, options] (label)}
              {#if options.length}
                <optgroup label={t(label)}>
                  {#each options as option (option.key)}<option value={option.key}>{t(`pack.migrate.kind.${option.kind}`)}: {option.name}</option>{/each}
                </optgroup>
              {/if}
            {/each}
          </select>
          <span class="pw-arrow" aria-hidden="true">&gt;</span>
          <select class="pk-field pk-select" bind:value={targetId} aria-label={t('pack.work.move_target')} data-pm="migrate-target">
            <option value="">{t('pack.work.move_target')}</option>
            {#each peers as machine (machine.install_id)}<option value={machine.install_id} disabled={refuses(machine)}>{machine.label || machine.install_id.slice(0, 8)}</option>{/each}
          </select>
          {#if !migrate.target}
            <button type="button" class="modal-btn modal-btn-confirm pk-act" disabled={!moveKey || !targetId} data-pm="migrate-go" onclick={startMove}>{t('pack.migrate.panel_go')}</button>
          {/if}
        </div>
        <MigrateWizard />
      </div>
    {/if}
  </div>
</section>
