<script lang="ts">
  import { Button, Checkbox, Field, IconButton, Select } from '../base';
  import ModalShell from '../launchpad/ModalShell.svelte';
  import { forkSessionTo } from './fork-to';
  import { t } from '../i18n/index.svelte';

  interface Props { sessionId: string; name: string; onClose: () => void }
  let { sessionId, name, onClose }: Props = $props();
  let provider = $state<'claude' | 'codex'>('codex');
  let model = $state('');
  let effort = $state('');
  let prompt = $state('');
  let forkName = $state('');
  let worktree = $state(false);
  let busy = $state(false);
  let error = $state('');

  const PROVIDERS = [{ value: 'codex', label: 'codex' }, { value: 'claude', label: 'claude' }];
  const efforts = $derived([
    { value: '', label: t('session.fork_to.default') },
    { value: 'low', label: 'low' }, { value: 'medium', label: 'medium' }, { value: 'high', label: 'high' },
    ...(provider === 'codex' ? [{ value: 'xhigh', label: 'xhigh' }, { value: 'max', label: 'max' }] : []),
  ]);

  async function create(): Promise<void> {
    if (busy) return;
    busy = true;
    error = '';
    try {
      await forkSessionTo(sessionId, { provider, model, effort, prompt, name: forkName, worktree });
      onClose();
    } catch (cause) {
      error = cause instanceof Error ? cause.message : t('session.fork_to.failed');
    } finally { busy = false; }
  }
</script>

<ModalShell title={t('session.fork_to.title')} overlayClass="text-prompt-modal na-flow" dismissable={!busy} onCancel={onClose}>
  {#snippet head()}
    <div class="text-prompt-modal__head">
      <span class="text-prompt-modal__verb">{t('session.fork_to.title')}</span>
      <IconButton variant="close" icon="close" label={t('modal.close')} disabled={busy} onclick={onClose} />
    </div>
  {/snippet}
  <p class="modal-description">{t('session.fork_to.source', { name })}</p>
  <Select id="fork-provider" label={t('session.fork_to.provider')} bind:value={provider} disabled={busy} options={PROVIDERS} />
  <Field id="fork-model" label={t('session.fork_to.model')} bind:value={model} disabled={busy} maxlength={200} placeholder={t('session.fork_to.default')} />
  <Select id="fork-effort" label={t('session.fork_to.effort')} bind:value={effort} disabled={busy} options={efforts} />
  <Field id="fork-name" label={t('session.fork_to.name')} bind:value={forkName} disabled={busy} maxlength={200} placeholder={t('session.fork_to.default')} />
  <Field id="fork-prompt" label={t('session.fork_to.prompt')} multiline bind:value={prompt} disabled={busy} maxlength={4000} />
  <Checkbox label={t('session.fork_to.worktree')} bind:checked={worktree} disabled={busy} />
  {#if error}<p role="alert">{error}</p>{/if}
  {#snippet footer()}
    <Button disabled={busy} onclick={onClose}>{t('session.fork_to.cancel')}</Button>
    <Button variant="confirm" data-fork-to-create disabled={busy} onclick={create}>{t('session.fork_to.create')}</Button>
  {/snippet}
</ModalShell>
