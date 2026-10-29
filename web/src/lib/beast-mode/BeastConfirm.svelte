<script lang="ts">
  import { Button, IconButton, Select } from '../base';

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
      <IconButton label={t('modal.close')} variant="close" icon="close" iconSize={14} data-modal-close onclick={() => close(null)} />
    </div>
  {/snippet}
  <p class="modal-description">{t('beast.confirm.body', { count: status?.pending_count ?? 0 })}</p>
  <p class="modal-description beast-risk" data-beast-risk>{t('beast.confirm.risk')}</p>
  <div class="beast-scope" data-beast-scope>
    <Check role="checkbox" label={t('beast.prompts.label')} hint={t('beast.prompts.hint')} checked={prompts}
      disabled={busy} onToggle={(next) => (prompts = next)} data-beast-prompts-check="" />
    <label class="beast-scope__off">
      <span class="pl-label">{t('beast.auto_off.label')}</span>
      <Select bind:value={hours} disabled={busy} data-beast-auto-off aria-label={t('beast.auto_off.label')}
        options={BEAST_AUTO_OFF_HOURS.map((choice) => ({ value: choice === null ? '' : String(choice), label: choice === null ? t('beast.auto_off.never') : t('beast.auto_off.hours', { count: choice }) }))} />
    </label>
  </div>
  {#if error}<p role="alert">{error}</p>{/if}
  {#snippet footer()}
    <Button disabled={busy} onclick={() => close(null)}>{t('beast.confirm.cancel')}</Button>
    <Button variant="danger" data-beast-confirm-go disabled={busy} onclick={arm}>{t('beast.confirm.arm')}</Button>
  {/snippet}
</ModalShell>

<style>
  @layer components {
    .beast-scope { display: flex; flex-direction: column; gap: var(--oc-space-2); margin-top: var(--oc-space-2); }
    .beast-scope__off { display: flex; align-items: center; gap: var(--oc-space-2); }
    .beast-risk { color: var(--oc-coral); }
  }
</style>
