<script lang="ts">
  import ViewMenu from '../drawer-tabs/ViewMenu.svelte';
  import NewSessionButton from '../drawer-tabs/NewSessionButton.svelte';
  import { t } from '../i18n/index.svelte';
</script>

<div class="sbr-controls" role="toolbar" aria-label={t('drawer.tabs.actions')}>
  <ViewMenu />
  <NewSessionButton />
</div>

<style>
  @layer components {
    .sbr-controls {
      display: inline-flex;
      align-items: center;
      gap: 2px;
    }

    .sbr-controls::after {
      content: '';
      width: var(--oc-border);
      height: 18px;
      margin: 0 var(--oc-space-1) 0 var(--oc-space-2);
      background: var(--oc-line-rule);
    }
  }
</style>
