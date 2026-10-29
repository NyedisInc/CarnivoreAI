<script lang="ts">
  import { t } from '../i18n/index.svelte';
  import { Button, Field } from '../base';
  import { activity, addOverSsh, check, computers } from './computers-store.svelte';
  import { codeCopy } from './computers-format';

  const STEPS = ['checking_host_key', 'connecting', 'hello', 'download', 'install', 'launch', 'wait_server', 'join_ready', 'join', 'joined'];

  const { prefill = null }: { prefill?: string | null } = $props();
  // svelte-ignore state_referenced_locally
  let target = $state(prefill ?? '');
  let portText = $state('');
  const port = $derived(/^\d{1,5}$/.test(portText.trim()) ? Number(portText.trim()) : null);
  const preview = $derived(activity.preview);
  const blockers = $derived(preview === null ? [] : preview.blockers);
  const keyChanged = $derived(preview !== null && preview.known === 'changed');
  const canAdd = $derived(preview !== null && !keyChanged && blockers.length === 0 && preview.reachable && activity.busy === null);
  const jobs = $derived(computers.data?.add_jobs ?? []);

  function onEdit(): void {
    activity.preview = null;
  }
</script>

<div class="cmp-region" data-cmp="ssh">
  <h3 class="pl-label">{t('computers.ssh.title')}</h3>
  <form class="cmp-form" onsubmit={(e) => { e.preventDefault(); void check(target.trim(), port); }}>
    <div class="cmp-field"><Field label={t('computers.ssh.target')} autocomplete="off" autocapitalize="off" spellcheck={false} bind:value={target}
      placeholder={t('computers.ssh.target_placeholder')} oninput={onEdit} data-cmp="ssh-target" /></div>
    <div class="cmp-field cmp-field--port"><Field label={t('computers.ssh.port')} inputmode="numeric" bind:value={portText} placeholder={t('computers.ssh.port_placeholder')}
      oninput={onEdit} data-cmp="ssh-port" /></div>
    <Button type="submit" data-cmp="ssh-check" disabled={target.trim() === '' || activity.busy !== null}>
      {activity.busy === 'preview' ? t('computers.ssh.checking') : t('computers.ssh.check')}</Button>
  </form>
  {#if preview !== null}
    <div data-cmp="preview">
      <p class="cmp-fp" data-cmp="host-key">{t('computers.ssh.host_key', { key: preview.host_key_sha256 })}</p>
      <p class="cmp-note" data-cmp="known">
        {preview.known === 'new' ? t('computers.ssh.new_key') : preview.known === 'same' ? t('computers.ssh.known_key') : t('computers.ssh.changed_key')}</p>
      {#each blockers as blocker (blocker)}
        <p class="cmp-blocker" data-blocker={blocker}>{codeCopy('computers.ssh.blocker', blocker, 'computers.error.failed')}</p>
      {/each}
      <div class="cmp-actions">
        <Button variant="confirm" data-cmp="ssh-add" disabled={!canAdd}
          onclick={() => void addOverSsh(target.trim(), port)}>{t('computers.ssh.add')}</Button>
      </div>
    </div>
  {/if}
  {#each jobs as job (job.id)}
    {@const at = job.step === null ? -1 : STEPS.indexOf(job.step)}
    <div class="cmp-job" data-job={job.id} data-state={job.state}>
      <p class="cmp-name">{job.target}</p>
      <ol class="cmp-steps">
        {#each STEPS as step, i (step)}
          <li data-step={step} data-done={i < at || job.state === 'joined'} data-now={i === at && job.error === null && job.state !== 'joined'}>
            {t(`computers.job.step.${step}`)}</li>
        {/each}
      </ol>
      {#if job.error !== null}
        <p class="cmp-blocker" data-cmp="job-error">{codeCopy('computers.job.error', job.error, 'computers.error.failed')}</p>
      {/if}
    </div>
  {/each}
</div>
