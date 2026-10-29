<script lang="ts">
  import Icon from './Icon.svelte';
  import { isGlobalWidget } from '../widgets/global-scope';

  let {
    name,
    widget = null,
    size = 16,
    strokeWidth = 1.5,
    fill = 'outline',
  }: { name: string; widget?: string | null; size?: number; strokeWidth?: number; fill?: 'outline' | 'solid' } = $props();

  const global = $derived(isGlobalWidget(widget));
  const mark = $derived(Math.max(8, Math.round(size * 0.6)));
</script>

{#if global}
  <span class="oc-wicon" data-widget-icon-global style={`width: ${size}px; height: ${size}px`}>
    <Icon {name} {size} {strokeWidth} {fill} />
    <span class="oc-wicon-globe" data-widget-globe style={`width: ${mark}px; height: ${mark}px`}>
      <Icon name="globe" size={mark} strokeWidth={2} />
    </span>
  </span>
{:else}
  <Icon {name} {size} {strokeWidth} {fill} />
{/if}

<style>
  @layer components {
    .oc-wicon { position: relative; display: inline-flex; flex: 0 0 auto; vertical-align: middle; }

    .oc-wicon-globe { position: absolute; right: -3px; bottom: -3px; display: inline-flex; align-items: center; justify-content: center; border-radius: 50%; background: var(--oc-ground-panel); color: currentColor; pointer-events: none; }
  }
</style>
