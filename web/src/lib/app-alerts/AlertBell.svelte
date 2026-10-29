<script lang="ts">
  import Icon from '../../opscenter/ui/Icon.svelte';
  import { t } from '../i18n/index.svelte';
  import AlertBadge from './AlertBadge.svelte';
  import { alertCenter } from './alerts.svelte';
  import { bellBadge, startAttentionSources } from '../attention-kinds/read.svelte';
  import { alertPanel, toggleAppAlerts } from './alert-panel.svelte';

  let { place = 'drawer' }: { place?: 'drawer' | 'rail' } = $props();

  let revealed = $state(false);
  $effect(() => {
    if (alertCenter.status === 'ok') revealed = true;
  });

  $effect(() => startAttentionSources());

  const badge = $derived(bellBadge());
  const label = $derived(badge.count > 0 ? t('app_alert.bell.count', { count: badge.count }) : t('app_alert.panel.title'));
</script>

{#if revealed && badge.count > 0}
  
  <button type="button" data-btn="quiet" data-size="icon" data-app-alert-bell={place}
    aria-label={label} data-tooltip={label} aria-expanded={alertPanel.open} aria-controls="app-alerts-panel"
    onclick={() => toggleAppAlerts()}>
    <Icon name="bell" size={16} />
    <AlertBadge />
  </button>
{/if}

<style>
  @layer components {
  [data-app-alert-bell] {
    position: relative;
    flex: 0 0 auto;
  }
  [data-app-alert-bell='drawer'] {
    --oc-ibtn-size: 28px;
  }
  }
</style>
