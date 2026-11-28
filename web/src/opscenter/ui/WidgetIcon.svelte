<script lang="ts">
  import Icon from './Icon.svelte';
  import { catalogApiImageUrl } from '../../lib/catalog/card-media';
  import { isGlobalWidget } from '../widgets/global-scope';
  import { pluginIconUrl } from './plugin-icon-registry.svelte';

  let {
    name,
    widget = null,
    size = 16,
    strokeWidth = 1.5,
    fill = 'outline',
  }: { name: string; widget?: string | null; size?: number; strokeWidth?: number; fill?: 'outline' | 'solid' } = $props();

  const global = $derived(isGlobalWidget(widget));
  const customApiUrl = $derived(pluginIconUrl(widget));
  let customSrc = $state<string | null>(null);

  $effect(() => {
    const url = customApiUrl;
    customSrc = null;
    if (!url) return;
    let cancelled = false;
    void catalogApiImageUrl(url).then((blobUrl) => {
      if (!cancelled && blobUrl) customSrc = blobUrl;
    });
    return () => {
      cancelled = true;
    };
  });

  const mark = $derived(Math.max(8, Math.round(size * 0.6)));
</script>

{#if global}
  <span class="oc-wicon" data-widget-icon-global style={`width: ${size}px; height: ${size}px`}>
    {#if customSrc}
      <img class="oc-wicon-img" src={customSrc} alt="" width={size} height={size} />
    {:else}
      <Icon {name} {size} {strokeWidth} {fill} />
    {/if}
    <span class="oc-wicon-globe" data-widget-globe style={`width: ${mark}px; height: ${mark}px`}>
      <Icon name="globe" size={mark} strokeWidth={2} />
    </span>
  </span>
{:else if customSrc}
  <img class="oc-wicon-img" src={customSrc} alt="" width={size} height={size} />
{:else}
  <Icon {name} {size} {strokeWidth} {fill} />
{/if}

<style>
  @layer components {
    .oc-wicon { position: relative; display: inline-flex; flex: 0 0 auto; vertical-align: middle; }

    .oc-wicon-img { display: block; flex: 0 0 auto; object-fit: contain; border-radius: var(--oc-radius-control); }

    .oc-wicon-globe { position: absolute; right: -3px; bottom: -3px; display: inline-flex; align-items: center; justify-content: center; border-radius: var(--oc-radius-circle); background: var(--oc-ground-panel); color: currentColor; pointer-events: none; }
  }
</style>
