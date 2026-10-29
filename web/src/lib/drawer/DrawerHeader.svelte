<script lang="ts">
  import IconButton from '../base/IconButton.svelte';
  import { t } from '../i18n/index.svelte';
</script>

<div class="session-sidebar-heading">
  <button type="button" id="session-sidebar-brand" class="session-sidebar-brand" aria-label={t('drawer.header.brand')}>
    <img src="/static/img/carnivore/carnivore-wordmark.png" srcset="/static/img/carnivore/carnivore-wordmark.png 1x, /static/img/carnivore/carnivore-wordmark@2x.png 2x" alt="" />
  </button>
  <div id="session-sidebar-topbar-controls" class="sbr-controls-slot"></div>
  <div id="session-sidebar-alerts" class="session-sidebar-alerts"></div>
</div>
<div class="session-sidebar-actions">
  <IconButton label={t('drawer.header.hide')} variant="quiet" id="session-sidebar-collapse" data-dh-key="">
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
      <rect x="3" y="3" width="18" height="18" rx="2" />
      <line x1="9" y1="3" x2="9" y2="21" />
      <path d="M4 4h4v16H4z" fill="currentColor" stroke="none" />
    </svg>
  </IconButton>
</div>

<style>
  @layer components {
    .session-sidebar-heading {
      gap: var(--oc-space-3);
    }

    .session-sidebar-actions {
      margin-left: var(--oc-space-1);
    }

    .session-sidebar-actions :global([data-dh-key]) {
      --oc-ibtn-size: 28px;
      flex-shrink: 0;
      border-radius: var(--oc-radius-sm);
      color: var(--oc-text-secondary);
    }

    .session-sidebar-actions :global([data-dh-key]:hover:not(:disabled)),
    .session-sidebar-actions :global([data-dh-key]:focus-visible) {
      background: var(--oc-ground-hover);
      color: var(--oc-text-primary);
    }
  }
</style>
