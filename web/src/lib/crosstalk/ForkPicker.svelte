<script lang="ts">
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
      <button type="button" class="modal-close" aria-label={t('modal.close')} disabled={busy} onclick={onClose}>×</button>
    </div>
  {/snippet}
  <p class="modal-description">{t('session.fork_to.source', { name })}</p>
  <label class="modal-label" for="fork-provider">{t('session.fork_to.provider')}</label>
  <select id="fork-provider" class="modal-input" bind:value={provider} disabled={busy}>
    <option value="codex">codex</option><option value="claude">claude</option>
  </select>
  <label class="modal-label" for="fork-model">{t('session.fork_to.model')}</label>
  <input id="fork-model" class="modal-input" bind:value={model} disabled={busy} maxlength="200" placeholder={t('session.fork_to.default')} />
  <label class="modal-label" for="fork-effort">{t('session.fork_to.effort')}</label>
  <select id="fork-effort" class="modal-input" bind:value={effort} disabled={busy}>
    <option value="">{t('session.fork_to.default')}</option>
    <option value="low">low</option><option value="medium">medium</option>
    <option value="high">high</option>{#if provider === 'codex'}<option value="xhigh">xhigh</option><option value="max">max</option>{/if}
  </select>
  <label class="modal-label" for="fork-name">{t('session.fork_to.name')}</label>
  <input id="fork-name" class="modal-input" bind:value={forkName} disabled={busy} maxlength="200" placeholder={t('session.fork_to.default')} />
  <label class="modal-label" for="fork-prompt">{t('session.fork_to.prompt')}</label>
  <textarea id="fork-prompt" class="modal-input" bind:value={prompt} disabled={busy} maxlength="4000"></textarea>
  <label class="modal-label"><input type="checkbox" bind:checked={worktree} disabled={busy} /> {t('session.fork_to.worktree')}</label>
  {#if error}<p role="alert">{error}</p>{/if}
  {#snippet footer()}
    <button type="button" class="modal-btn modal-btn-secondary" disabled={busy} onclick={onClose}>{t('session.fork_to.cancel')}</button>
    <button type="button" class="modal-btn modal-btn-confirm" data-fork-to-create disabled={busy} onclick={create}>{t('session.fork_to.create')}</button>
  {/snippet}
</ModalShell>
