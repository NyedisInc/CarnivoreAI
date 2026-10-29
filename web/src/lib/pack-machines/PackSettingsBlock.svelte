<script lang="ts">
  import { onMount } from 'svelte';
  import './pack-machines.css';
  import { t } from '../i18n/index.svelte';
  import Check from '../../opscenter/ui/Check.svelte';
  import RouteRow from '../byoai/RouteRow.svelte';
  import { attach } from '../byoai/store.svelte';
  import { packActivity, packMachines, updateSettings } from './pack-machines-store.svelte';

  const settings = $derived(packMachines.data?.settings);
  const enhanced = $derived(settings?.placement_mode === 'enhanced');
  const model = $derived(settings?.placement_model ?? null);
  const master = $derived(packMachines.data?.machines.find((m) => m.is_master));
  let modelError = $state<string | null>(null);

  onMount(() => attach());

  function setModel(target: { connection: string; model?: string | null }): void {
    if (!target.model) {
      modelError = t('pack.machines.model_needs_model');
      return;
    }
    modelError = null;
    void updateSettings({ placement_model: { connection: target.connection, model: target.model } });
  }
</script>

{#if settings}
  <div class="pm-settings pw-group" data-pm="settings">
    <div class="pw-grouphead">
      <h3 class="pl-label">{t('pack.work.placement_title')}</h3>
      <span class="pw-tag" title={t('pack.machines.settings_held', { master: master?.label || master?.install_id.slice(0, 8) || '-' })} data-pm="held-tag">{t('pack.work.held_tag')}</span>
    </div>
    <Check label={t('pack.machines.auto_distribute')} hint={t('pack.machines.auto_distribute_help')}
      checked={settings.auto_distribute} role="switch" disabled={packActivity.busy !== null} data-pm="auto-distribute"
      onToggle={(next) => void updateSettings({ auto_distribute: next })} />
    <Check label={t('pack.machines.enhanced')} hint={t('pack.machines.enhanced_help')} checked={enhanced} role="switch"
      disabled={packActivity.busy !== null} data-pm="enhanced"
      onToggle={(next) => void updateSettings({ placement_mode: next ? 'enhanced' : 'stats' })} />
    {#if enhanced}
      <div class="pm-model pw-model" data-pm="placement-model">
        <RouteRow name={t('pack.machines.placement_model')} capability="decide"
          target={model ? { connection: model.connection, model: model.model, voice: null } : null}
          busy={packActivity.busy !== null} onSet={setModel} unsetLabel={t('pack.work.connection_default')}
          modelPlaceholder={t('pack.work.model_default')}
          onClear={() => void updateSettings({ placement_model: null })} />
        {#if modelError}<p class="pm-error" role="alert" data-pm="model-error">{modelError}</p>{/if}
      </div>
    {/if}
  </div>
{/if}
