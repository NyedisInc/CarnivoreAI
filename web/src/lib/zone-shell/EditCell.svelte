<script lang="ts">
  import type { Snippet } from 'svelte';
  import Icon from '../../opscenter/ui/Icon.svelte';
  import { t } from '../i18n/index.svelte';
  import { buttonAttrs } from '../base/classes';

  let { hidden, name, ontoggle, children }: { hidden: boolean; name: string; ontoggle: () => void; children: Snippet } = $props();
</script>

<span class="oc-edit-cell" data-hidden={hidden ? '' : undefined} data-edit-cell>
  {@render children()}
  <button type="button" class="oc-edit-badge" {...buttonAttrs('quiet', 'icon')} data-menu-nodrag data-edit-badge data-state={hidden ? 'hidden' : 'shown'}
    aria-label={t(hidden ? 'sidebar.rail.icon.show' : 'sidebar.rail.icon.hide', { name })} onclick={ontoggle}>
    <Icon name={hidden ? 'eye-off' : 'eye'} size={9} strokeWidth={2.5} />
  </button>
</span>

<style>
  @layer components {
    .oc-edit-cell {
      position: relative;
      display: inline-flex;
      flex: none;
    }

    .oc-edit-cell::before {
      content: '';
      position: absolute;
      inset: 0;
      border: var(--oc-border) dashed var(--oc-cyan);
      border-radius: var(--oc-radius-sm);
      pointer-events: none;
    }

    .oc-edit-cell[data-hidden] > :not(.oc-edit-badge) {
      opacity: 0.4;
    }

    .oc-edit-badge {
      position: absolute;
      top: -4px;
      right: -4px;
      z-index: 2;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 13px;
      height: 13px;
      padding: 0;
      border: 0;
      border-radius: var(--oc-radius-sm);
      background: var(--oc-ground-titlerow);
      box-shadow: inset 0 0 0 var(--oc-border) var(--oc-line-panel);
      color: var(--oc-cyan);
      cursor: pointer;
    }

    .oc-edit-badge[data-state='hidden'] {
      color: var(--oc-text-dim);
    }
  }
</style>
