<!-- did not answer -->
<script lang="ts">
  import { onMount } from 'svelte';
  import { t } from '../i18n/index.svelte';
  import { nonEmptyErrorMessageOr } from '../errors/failure-reason';
  import { openModal } from '../modal';
  import Button from '../base/Button.svelte';
  import Switch from '../base/Switch.svelte';
  import HostKeyConfirm from './HostKeyConfirm.svelte';
  import { hostKeyShown, sshTargetsApi, type HostKeyShown, type SshTargetsApi } from './ssh-targets-api';
  import { isKeyChanged, loadSshTargets, markChanged, sshTargets, takeTarget, targetOf } from './ssh-targets-store.svelte';
  import { shownState, stateWords } from './ssh-state-words';

  const { hostKey, api = sshTargetsApi }: { hostKey: string; api?: SshTargetsApi } = $props();
  const MAX_ASKS = 3;

  let busy = $state(false);
  let error = $state<string | null>(null);
  let notFresh = $state(false);
  let askForget = $state(false);
  let forgot = $state<string | null>(null);
  const target = $derived(targetOf(hostKey));
  const changed = $derived(sshTargets.changed[hostKey] === true);
  const targetState = $derived(target ? shownState(target, changed) : 'off');
  const locked = $derived(target !== null && (target.state === 'not_a_job_target' || target.state === 'host_disabled') && !target.takes_work);
  const can = $derived(target?.can ?? null);
  const wsl = $derived((can?.labels ?? []).includes('wsl'));
  const gpus = $derived(can?.gpus ?? []);
  const tools = $derived(Object.entries(can?.tools ?? {}).filter(([, has]) => has).map(([name]) => name));
  const gpuLine = (g: { model?: string | null; vram_gb?: number | null }): string =>
    `${g.model ?? '-'}${g.vram_gb != null ? `, ${t('pack.ssh.fact.gb', { n: Math.round(g.vram_gb) })}` : ''}`;

  onMount(() => { void loadSshTargets(api); });

  async function confirmKey(first: HostKeyShown, label: string): Promise<void> {
    let shown: HostKeyShown | null = first;
    for (let asks = 0; shown && asks < MAX_ASKS; asks += 1) {
      if (shown.known === 'changed') markChanged(hostKey);
      const fingerprint = await openModal<string, { label: string; shown: HostKeyShown }>(HostKeyConfirm, { label, shown });
      if (!fingerprint) return;
      try {
        takeTarget(await api.set(hostKey, { takes_work: true, host_key_sha256: fingerprint }));
        return;
      } catch (failure) {
        shown = hostKeyShown(failure);
        if (!shown) { error = nonEmptyErrorMessageOr(failure, t('pack.ssh.error.failed')); return; }
      }
    }
  }

  async function setWork(next: boolean): Promise<void> {
    if (busy || !target) return;
    busy = true;
    error = null;
    try {
      takeTarget(await api.set(hostKey, { takes_work: next }));
    } catch (failure) {
      const shown = next ? hostKeyShown(failure) : null;
      if (shown) await confirmKey(shown, target.label);
      else error = nonEmptyErrorMessageOr(failure, t('pack.ssh.error.failed'));
    } finally {
      busy = false;
    }
  }

  async function forget(): Promise<void> {
    if (busy) return;
    busy = true;
    error = null;
    askForget = false;
    try {
      const done = await api.forget(hostKey);
      forgot = done.kept.length > 0 || done.refused.length > 0 ? t('pack.ssh.forget_some') : t('pack.ssh.forget_done');
    } catch (failure) {
      error = nonEmptyErrorMessageOr(failure, t('pack.ssh.error.failed'));
    } finally {
      busy = false;
    }
  }

  async function check(): Promise<void> {
    if (busy) return;
    busy = true;
    error = null;
    try {
      const answer = await api.check(hostKey);
      notFresh = !answer.fresh;
      takeTarget(answer.target);
    } catch (failure) {
      if (isKeyChanged(failure)) markChanged(hostKey);
      error = nonEmptyErrorMessageOr(failure, t('pack.ssh.error.failed'));
    } finally {
      busy = false;
    }
  }
</script>

{#if target}
  <section class="m1-sec" data-ssh="block" data-host-key={hostKey}>
    <h3 class="pp-k">{t('pack.ssh.title')}</h3>
    <Switch label={t('pack.ssh.switch')} hint={t('pack.ssh.switch_hint')} disabled={busy || locked}
      bind:checked={() => target.takes_work, (next) => void setWork(next)} data-ssh="takes-work" />
    <p class="pp-hint" data-ssh="state" data-state={targetState}>{stateWords(target, changed)}</p>
    {#if targetState === 'host_key_changed'}
      <p class="pp-warn" role="status" data-ssh="changed-way">{t('pack.ssh.changed_way')}</p>
      <div class="pp-ssh__acts"><Button size="sm" disabled={busy} data-ssh="reconfirm" onclick={() => void setWork(true)}>{t('pack.ssh.reconfirm')}</Button></div>
    {/if}
    {#if can}
      <dl class="pp-facts" data-ssh="facts">
        <dt>{t('pack.ssh.fact.os')}</dt><dd>{wsl ? t('pack.ssh.fact.os_wsl', { os: can.os ?? '-' }) : (can.os ?? '-')}{can.os_version ? ` ${can.os_version}` : ''}</dd>
        <dt>{t('pack.ssh.fact.cores')}</dt><dd>{can.cores ?? '-'}</dd>
        <dt>{t('pack.ssh.fact.memory')}</dt><dd>{can.mem_gb != null ? t('pack.ssh.fact.gb', { n: Math.round(can.mem_gb) }) : '-'}</dd>
        <dt>{t('pack.ssh.fact.gpu')}</dt><dd>{gpus.length > 0 ? gpus.map(gpuLine).join('; ') : '-'}</dd>
        <dt>{t('pack.ssh.fact.tools')}</dt><dd>{tools.length > 0 ? tools.join(', ') : '-'}</dd>
      </dl>
    {/if}
    <div class="pp-ssh__acts">
      <Button size="sm" disabled={busy || targetState === 'not_a_job_target' || targetState === 'host_disabled'} data-ssh="check" onclick={() => void check()}>{t('pack.ssh.check')}</Button>
    </div>
    {#if target.pinned}
      <div class="pp-ssh__acts">
        {#if askForget}
          <span class="pp-hint" data-ssh="forget-ask">{t('pack.ssh.forget_ask')}</span>
          <Button size="sm" variant="danger" disabled={busy} data-ssh="forget-go" onclick={() => void forget()}>{t('pack.ssh.forget_go')}</Button>
          <Button size="sm" disabled={busy} data-ssh="forget-cancel" onclick={() => { askForget = false; }}>{t('pack.ssh.forget_cancel')}</Button>
        {:else}
          <Button size="sm" disabled={busy || target.live_jobs > 0} data-ssh="forget" onclick={() => { askForget = true; forgot = null; }}>{t('pack.ssh.forget')}</Button>
        {/if}
      </div>
      {#if forgot}<p class="pp-hint" role="status" data-ssh="forgot">{forgot}</p>{/if}
    {/if}
    {#if notFresh}<p class="pp-hint" role="status" data-ssh="not-fresh">{t('pack.ssh.check_not_fresh')}</p>{/if}
    {#if error}<p class="pp-err" role="alert" data-ssh="error">{error}</p>{/if}
  </section>
{/if}
