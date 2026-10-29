<script lang="ts">
  import { t } from '../i18n/index.svelte';
  import Check from '../../opscenter/ui/Check.svelte';
  import ModalShell from '../launchpad/ModalShell.svelte';
  import { armBeast, BEAST_AUTO_OFF_HOURS, type BeastStatus } from './control.svelte';

  interface Props {
    status: BeastStatus | null;
    close: (value: boolean | null) => void;
  }

  const { status, close }: Props = $props();

  let busy = $state(false);
  let error = $state('');
  let prompts = $state(false);
  let hours = $state<string>('');

  async function arm(): Promise<void> {
    if (busy) return;
    busy = true;
    error = '';
    try {
      await armBeast(prompts, hours === '' ? null : Number(hours));
      close(true);
    } catch (cause) {
      error = cause instanceof Error ? cause.message : t('beast.error');
    } finally {
      busy = false;
    }
  }
</script>

<ModalShell title={t('beast.confirm.title')} overlayClass="text-prompt-modal na-flow" onCancel={() => close(null)}>
  {#snippet head()}
    <div class="text-prompt-modal__head">
      <span class="text-prompt-modal__verb">{t('beast.confirm.title')}</span>
      <button type="button" class="modal-close" aria-label={t('modal.close')} onclick={() => close(null)}>×</button>
    </div>
  {/snippet}
  <p class="modal-description">{t('beast.confirm.body', { count: status?.pending_count ?? 0 })}</p>
  <p class="modal-description beast-risk" data-beast-risk>{t('beast.confirm.risk')}</p>
  <div class="beast-scope" data-beast-scope>
    <Check role="checkbox" label={t('beast.prompts.label')} hint={t('beast.prompts.hint')} checked={prompts}
      disabled={busy} onToggle={(next) => (prompts = next)} data-beast-prompts-check="" />
    <label class="beast-scope__off">
      <span class="pl-label">{t('beast.auto_off.label')}</span>
      <select class="oc-field" bind:value={hours} disabled={busy} data-beast-auto-off>
        {#each BEAST_AUTO_OFF_HOURS as choice (choice ?? 'never')}
          <option value={choice === null ? '' : String(choice)}>{choice === null ? t('beast.auto_off.never') : t('beast.auto_off.hours', { count: choice })}</option>
        {/each}
      </select>
    </label>
  </div>
  {#if error}<p role="alert">{error}</p>{/if}
  {#snippet footer()}
    <button type="button" class="modal-btn modal-btn-secondary" disabled={busy} onclick={() => close(null)}>{t('beast.confirm.cancel')}</button>
    <button type="button" class="modal-btn modal-btn-danger" data-beast-confirm-go disabled={busy} onclick={arm}>{t('beast.confirm.arm')}</button>
  {/snippet}
</ModalShell>

<style>
  @layer components {
    .beast-scope { display: flex; flex-direction: column; gap: var(--oc-space-2); margin-top: var(--oc-space-2); }
    .beast-scope__off { display: flex; align-items: center; gap: var(--oc-space-2); }
    .beast-risk { color: var(--oc-coral); }
  }
</style>
