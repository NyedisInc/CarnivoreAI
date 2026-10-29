<script lang="ts">
  import { t } from '../i18n/index.svelte';
  import { alertCenter } from './alerts.svelte';
  import { badgeFor } from './alerts-model';

  const badge = $derived(badgeFor(alertCenter.counts));
</script>

{#if badge.severity}
  <span class="aa-dot" class:aa-dot--error={badge.severity === 'error'} class:aa-dot--warn={badge.severity === 'warn'}
    data-app-alert-dot={badge.severity} role="img" aria-label={t('app_alert.dot.label')}></span>
{/if}

<style>
  @layer components {
  .aa-dot {
    position: absolute;
    top: 0;
    right: 0;
    width: 7px;
    height: 7px;
    border-radius: var(--oc-radius-sm, 2px);
    box-shadow: 0 0 0 var(--oc-border, 1px) var(--oc-ground-chrome);
    pointer-events: none;
  }
  .aa-dot--error { background: var(--oc-coral); }
  .aa-dot--warn { background: var(--oc-yellow); }
  }
</style>
