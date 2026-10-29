<script lang="ts">
  /* could not */
  import type { LayoutStore } from './layout.svelte';

  let { store }: { store: LayoutStore } = $props();
  import { t } from '../../lib/i18n/index.svelte';
  import { dismissRefusal, placementRefusal } from '../widgets/chrome/refusal-toast.svelte';
</script>

<div class="oc-visually-hidden" aria-live="polite" aria-atomic="true">{store.state.announcement}</div>

{#if placementRefusal.line}
  
  <div class="oc-notice oc-notice--refusal" role="status" data-placement-refusal>
    <span class="oc-notice-text">{placementRefusal.line}</span>
    <button type="button" class="oc-notice-close" onclick={dismissRefusal} aria-label={t('layout_editor.refuse.dismiss')}>
      <span aria-hidden="true">×</span>
    </button>
  </div>
{:else if store.state.warning}
  <div class="oc-notice" role="status">
    <span class="oc-notice-text">{store.state.warning}</span>
    <button type="button" class="oc-notice-close" onclick={() => store.setWarning('')} aria-label={t('opscenter.notice.dismiss')}>
      <span aria-hidden="true">×</span>
    </button>
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

    .oc-notice-close {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 20px;
      height: 20px;
      padding: 0;
      background: none;
      border: 0;
      border-radius: var(--oc-radius-sm);
      color: var(--oc-text-dim);
      font: inherit;
      font-size: 15px;
      cursor: pointer;
    }

    .oc-notice-close:hover {
      background: var(--oc-ground-hover);
      color: var(--oc-text-primary);
    }

    @media (max-width: 1023px) {
      .oc-notice-close {
        min-width: var(--oc-tap);
        min-height: var(--oc-tap);
      }
  }
  }
</style>
