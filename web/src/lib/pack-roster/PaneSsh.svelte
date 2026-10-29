
<script lang="ts">
  import { onMount } from 'svelte';
  import { openModal } from '../modal';
  import { t } from '../i18n/index.svelte';
  import FacetSelect from '../../opscenter/ui/FacetSelect.svelte';
  import FedConfirmModal from '../hosts-page/FedConfirmModal.svelte';
  import AddHostModal from '../hosts-page/AddHostModal.svelte';
  import { ageWords } from '../computers/computers-format';
  import { probeVerdict, type HostRow } from '../hosts-page/hosts-adapter';
  import { loginOf, sshCommand, type RosterComputer } from './roster-model';
  import { hosts, linkHost, probeHost, refreshRoster, removeHost, rosterActivity, setHostEnabled } from './roster-store.svelte';
  import { openAdd, rosterUi } from './roster-ui.svelte';

  const { c, computers, nowMs }: { c: RosterComputer; computers: readonly RosterComputer[]; nowMs: number } = $props();
  const h = $derived(c.host);
  onMount(() => { void hosts.refresh(true); });
  let copied = $state<string | null>(null);
  const busy = $derived(rosterActivity.busy !== null);
  const why = $derived(h === null ? null : h.local ? t('roster.ssh.refuse_self') : h.session_count > 0 ? t('roster.ssh.refuse_sessions', { name: c.name, n: h.session_count }) : null);
  const options = $derived([
    ...(c.matchedBy === 'target' || c.matchedBy === null ? [{ value: '', label: t('roster.match.guess_option') }] : []),
    ...computers.filter((x) => x.kind !== 'ssh-only' || x.id === c.id).map((x) => ({ value: x.id, label: x.name })),
  ]);
  const current = $derived(c.matchedBy === 'link' ? c.id : '');

  const fact = (v: string | number | null | undefined): string => (v === null || v === undefined || v === '' ? '-' : String(v));

  async function copy(host: HostRow): Promise<void> {
    const cmd = sshCommand(host);
    try {
      await navigator.clipboard.writeText(cmd);
      copied = t('roster.ssh.copied', { command: cmd });
    } catch {
      copied = t('roster.ssh.copy_failed');
    }
  }

  async function pick(host: HostRow, value: string): Promise<void> {
    await linkHost(host.key, value === '' ? null : value);
  }

  async function remove(host: HostRow): Promise<void> {
    const yes = await openModal<true, { title: string; body: string; confirmLabel: string }>(FedConfirmModal, { title: t('roster.ssh.remove'), body: t('roster.ssh.remove_body'), confirmLabel: t('roster.ssh.remove') });
    if (yes) await removeHost(host.key);
  }

  async function reach(): Promise<void> {
    const row = await openModal<HostRow, { initial: { label: string; ssh_target: string } }>(AddHostModal, { initial: { label: c.name, ssh_target: '' } });
    if (row) await refreshRoster();
  }

  function install(host: HostRow): void {
    rosterUi.prefillLogin = host.ssh_target;
    openAdd('ssh');
  }
</script>

{#if !h}
  <p class="pp-hint">{t('roster.ssh.not_reached')}</p>
  <div class="pp-acts" data-act="reach"><button type="button" class="oc-btn oc-btn--confirm" onclick={() => void reach()}>{t('roster.ssh.reach')}</button></div>
{:else}
  <section class="m1-sec pp-ssh" data-host-key={h.key}>
    <div class="pp-ssh__head"><div class="pp-swrow"><span class="pp-swrow__label">{t('roster.ssh.enabled')}</span>
      <button type="button" class="pp-sw" role="switch" aria-checked={h.enabled} aria-label={t('roster.ssh.enable_for', { name: c.name })} data-act="enable" disabled={busy || h.local}
        onclick={() => void setHostEnabled(h.key, !h.enabled)}><i></i></button></div></div>
    <dl class="pp-facts">
      <dt>{t('roster.link.key')}</dt><dd>{h.key}</dd>
      <dt>{t('roster.fact.ssh_target')}</dt><dd>{fact(loginOf(h))}</dd>
      <dt>{t('roster.fact.port')}</dt><dd>{h.ssh_port ?? t('roster.fact.port_default')}</dd>
      <dt>{t('roster.fact.socket')}</dt><dd>{fact(h.socket)}</dd>
      <dt>{t('roster.ssh.sessions')}</dt><dd>{h.session_count}</dd>
      <dt>{t('roster.ssh.probe_state')}</dt><dd>{probeVerdict(h.probe_state, t)}</dd>
      <dt>{t('roster.ssh.probe_detail')}</dt><dd>{fact(h.probe_detail)}</dd>
      <dt>{t('roster.ssh.probed_at')}</dt><dd>{h.probed_at ? ageWords(h.probed_at, nowMs) : t('roster.ssh.never')}</dd>
      <dt>{t('roster.fact.tmux_version')}</dt><dd>{fact(h.tmux_version)}</dd>
      <dt>{t('roster.ssh.login_shell')}</dt><dd>{fact(h.login_shell)}</dd>
      <dt>{t('roster.ssh.machine_id')}</dt><dd>{fact(h.machine_id)}</dd>
      <dt>{t('roster.ssh.remote_carnivore')}</dt><dd>{h.remote_carnivore ? t('roster.ssh.yes') : t('roster.ssh.no')}</dd>
    </dl>
    <div class="pp-ssh__acts">
      <button type="button" class="oc-btn oc-btn--sm" data-act="probe" disabled={busy} onclick={() => void probeHost(h.key)}>
        {rosterActivity.busy === `probe:${h.key}` ? t('roster.ssh.probing') : t('roster.ssh.probe')}</button>
      <button type="button" class="oc-btn oc-btn--sm pp-destroy" data-act="remove-host" disabled={busy || why !== null} title={why ?? undefined} onclick={() => void remove(h)}>{t('roster.ssh.remove')}</button>
    </div>
    {#if why}<p class="pp-hint">{t('roster.ssh.refused', { why })}</p>{/if}
    {#if rosterActivity.error}<p class="pp-err" role="alert">{rosterActivity.error}</p>{/if}
  </section>
  {#if !h.local}
    <div class="m1-copyssh" data-act="copyssh"><code class="pp-wrap">{sshCommand(h)}</code>
      <button type="button" class="oc-btn oc-btn--sm" onclick={() => void copy(h)}>{t('roster.ssh.copy')}</button></div>
    {#if copied}<p class="pp-hint" role="status">{copied}</p>{/if}
    <div class="m1-match" data-act="match"><span class="pp-k">{t('roster.match.k')}</span>
      <FacetSelect label={t('roster.census.col_computer')} value={current} {options} onChange={(v) => void pick(h, v)} />
      <p class="pp-hint m1-match-note">{c.matchedBy === 'link' ? t('roster.match.linked') : t('roster.match.guess', { target: h.ssh_target ?? '' })}</p></div>
  {/if}
  {#if c.kind === 'ssh-only'}
    <div class="m1-install" data-act="install"><p class="pp-hint">{t('roster.ssh.install_note')}</p>
      <button type="button" class="oc-btn oc-btn--confirm" onclick={() => install(h)}>{t('roster.ssh.install')}</button></div>
  {/if}
{/if}
