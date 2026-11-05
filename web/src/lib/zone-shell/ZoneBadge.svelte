<script lang="ts">
  import Icon from '../../opscenter/ui/Icon.svelte';

  let { global = false, markPx = 8 }: { global?: boolean; markPx?: number } = $props();
</script>

{#if global}
  <span class="zone-badge-globe" data-widget-globe style={`width: ${markPx}px; height: ${markPx}px`} aria-hidden="true"><Icon name="globe" size={markPx} strokeWidth={2} /></span>
{/if}

<style>
  @layer components {
    .zone-badge-globe {
      position: absolute;
      right: 1px;
      bottom: 1px;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      border-radius: 50%;
      background: var(--oc-ground-panel);
      color: currentColor;
      pointer-events: none;
    }
  }
</style>
