<script lang="ts">
  import type { LayoutStore } from './layout.svelte';

  let { store }: { store: LayoutStore } = $props();
  import { t } from '../../lib/i18n/index.svelte';
  import { IconButton } from '../../lib/base';
  import { dismissRefusal, placementRefusal } from '../widgets/chrome/refusal-toast.svelte';
</script>

<div class="oc-visually-hidden" aria-live="polite" aria-atomic="true">{store.state.announcement}</div>

{#if placementRefusal.line}
  
  <div class="oc-notice oc-notice--refusal" role="status" data-placement-refusal>
    <span class="oc-notice-text">{placementRefusal.line}</span>
    <IconButton label={t('layout_editor.refuse.dismiss')} variant="close" icon="close" onclick={dismissRefusal} />
  </div>
{:else if store.state.warning}
  <div class="oc-notice" role="status">
    <span class="oc-notice-text">{store.state.warning}</span>
    <IconButton label={t('opscenter.notice.dismiss')} variant="close" icon="close" onclick={() => store.setWarning('')} />
  </div>
{/if}

<style>
  @layer components {
    .oc-notice {
      position: fixed;
      right: 12px;
      bottom: calc(12px + env(safe-area-inset-bottom, 0px));
      z-index: 55;
      display: flex;
      align-items: center;
      gap: 10px;
      max-width: min(420px, calc(100vw - 24px));
      padding: var(--oc-space-2) var(--oc-space-2) var(--oc-space-2) var(--oc-space-3);
      background: var(--oc-ground-raised);
      border: var(--oc-border) solid var(--oc-line-panel);
      border-left: 2px solid var(--oc-orange);
      border-radius: var(--oc-radius-sm);
      color: var(--oc-text-secondary);
      font-size: var(--oc-fs-label);
    }

    .oc-notice--refusal {
      z-index: 60;
      right: auto;
      left: 50%;
      transform: translateX(-50%);
      border-left-color: var(--oc-cyan);
    }

    .oc-notice-text {
      min-width: 0;
    }
  }
</style>
