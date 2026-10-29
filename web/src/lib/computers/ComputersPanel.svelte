<script lang="ts">
  import { onDestroy } from 'svelte';
  import '../ledger/ledger-chrome.css';
  import './computers.css';
  import '../pack-machines/pack-settings.css';
  import { t } from '../i18n/index.svelte';
  import AddOverSsh from './AddOverSsh.svelte';
  import ComputerRow from './ComputerRow.svelte';
  import InviteCard from './InviteCard.svelte';
  import JoinPack from './JoinPack.svelte';
  import PackNameField from './PackNameField.svelte';
  import { activity, addComputer, computers, leave, stopJoinPoll } from './computers-store.svelte';
  import { ageWords, stateWords } from './computers-format';
  import { packMachines } from '../pack-machines/pack-machines-store.svelte';

  let nowMs = $state(Date.now());
  const tick = setInterval(() => (nowMs = Date.now()), 30000);
  onDestroy(() => {
    clearInterval(tick);
    stopJoinPoll();
  });

  let leaving = $state(false);
  const view = $derived(computers.data);
  const role = $derived(view?.self.role ?? 'standalone');
  const main = $derived(view?.self.main ?? null);
  const mainName = $derived(main?.label ?? t('computers.join.main_fallback'));
  const rows = $derived.by(() => {
    const entries = new Map((view?.computers ?? []).map((c) => [c.install_id, c]));
    const machines = [...(packMachines.data?.machines ?? [])].sort((a, b) => Number(b.is_self) - Number(a.is_self));
    const known = new Set(machines.map((m) => m.install_id));
    return [
      ...machines.map((machine) => ({ machine, computer: entries.get(machine.install_id) ?? null })),
      ...(view?.computers ?? []).filter((c) => !known.has(c.install_id)).map((computer) => ({ machine: null, computer })),
    ];
  });
  const alpha = $derived((packMachines.data?.machines ?? []).some((m) => m.is_self && m.is_master));
  const linkNote = $derived(view?.self.link.state === 'port_busy' ? 'port_busy' : view?.self.link.state === 'off_loopback' ? 'off_loopback' : null);
</script>

<section class="cmp-panel pl-panel pledger" aria-labelledby="cmp-title" data-computers>
  <div class="pl-titlebar">
    <h2 class="pl-title" id="cmp-title">{t('computers.title')}</h2>
    <span class="cmp-spacer"></span>
    {#if role !== 'member'}
      <button type="button" class="modal-btn modal-btn-confirm" data-cmp="add" disabled={activity.busy !== null} onclick={() => void addComputer()}>
        {t('computers.add')}</button>
    {/if}
  </div>
  <div class="cmp-body">
    {#if activity.error}<p class="cmp-error" role="alert" data-cmp="error">{activity.error}</p>{/if}
    {#if activity.notTold}
      <p class="cmp-note" role="status" data-cmp="not-told">
        {activity.notTold === 'main' ? t('computers.member.main_not_sent') : t('computers.row.not_sent', { label: activity.notTold })}</p>
    {/if}
    {#if !view}
      <p class="cmp-note">{t('computers.loading')}</p>
    {:else if role === 'member'}
      <div class="cmp-region" data-cmp="member">
        <p class="cmp-name" data-cmp="member-line">{t('computers.member.joined', { main: mainName })}</p>
        {#if view.self.link.state === 'port_busy'}<p class="cmp-note" data-cmp="link-note">{t('computers.link.port_busy')}</p>{/if}
        {#if main}
          <p class="cmp-meta" data-cmp="member-link">{t('computers.member.link', { state: stateWords(main.state), age: ageWords(main.last_link_at, nowMs) })}</p>
          {#if main.reachable_note}<p class="cmp-note" data-cmp="unreachable">{t('computers.member.unreachable_hours')}</p>{/if}
        {/if}
        {#if !leaving}
          <div class="cmp-actions">
            <button type="button" class="modal-btn modal-btn-danger" data-cmp="leave" disabled={activity.busy !== null} onclick={() => (leaving = true)}>
              {t('computers.member.leave')}</button>
          </div>
        {:else}
          <div class="cmp-confirm" data-cmp="leave-confirm">
            <p class="cmp-note">{t('computers.member.leave_confirm', { main: mainName })}</p>
            <div class="cmp-actions">
              <button type="button" class="modal-btn modal-btn-secondary" onclick={() => (leaving = false)}>{t('computers.row.cancel')}</button>
              <button type="button" class="modal-btn modal-btn-danger" data-cmp="leave-yes" disabled={activity.busy !== null}
                onclick={() => void leave().then(() => (leaving = false))}>{t('computers.member.leave')}</button>
            </div>
          </div>
        {/if}
      </div>
      <div class="cmp-region" data-cmp="members">
        <ul class="cmp-list">
          {#each rows as row (row.machine?.install_id ?? row.computer?.install_id)}
            <ComputerRow {...row} {nowMs} busy={activity.busy !== null} />
          {/each}
        </ul>
      </div>
    {:else}
      {#if alpha}<PackNameField />{/if}
      {#if linkNote}<p class="cmp-note" data-cmp="link-note">{t(`computers.link.${linkNote}`)}</p>{/if}
      <div class="cmp-region" data-cmp="list">
        {#if rows.length === 0}
          <p class="cmp-note">{t('computers.empty')}</p>
        {:else}
          <ul class="cmp-list">
            {#each rows as row (row.machine?.install_id ?? row.computer?.install_id)}
              <ComputerRow {...row} {nowMs} busy={activity.busy !== null} />
            {/each}
          </ul>
        {/if}
        <p class="cmp-note">{t('computers.footer.awake')}</p>
      </div>
      <InviteCard />
      <AddOverSsh />
      {#if role === 'standalone'}<JoinPack />{/if}
    {/if}
  </div>
</section>
