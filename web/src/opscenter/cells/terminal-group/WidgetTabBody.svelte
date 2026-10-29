<script lang="ts">
  import { t } from '../../../lib/i18n/index.svelte';
  import State from '../../../lib/base/State.svelte';
  import PlacementBody from '../../../lib/zone-shell/PlacementBody.svelte';
  import type { PlacementSource } from '../../../lib/zone-shell/source';
  import { widgetIdOfTab } from '../../engine/widget-tabs';
  import { widgetTabBinding } from './widget-tab-item';
  import { widgetTabOptions } from './widget-tab-source.svelte';

  let { tab, source }: { tab: string; source: PlacementSource } = $props();

  const widgetId = $derived(widgetIdOfTab(tab));
  const binding = $derived(widgetId === null ? null : widgetTabBinding(widgetId));
</script>

<div class="oc-wt" data-widget-tab={widgetId ?? undefined}>
  {#if binding}
    <PlacementBody host="tab" manifest={binding.widget} view={binding.view} options={widgetTabOptions(tab)} placementKey={tab} {source} />
  {:else}
    <State inline title={t('opscenter.tabs.widget_gone')} />
  {/if}
</div>

<style>
  @layer components {
    .oc-wt {
      position: relative;
      display: flex;
      flex: 1 1 auto;
      flex-direction: column;
      width: 100%;
      min-width: 0;
      min-height: 0;
      background: var(--oc-ground-page);
      color: var(--oc-text-primary);
      font-family: var(--oc-font, var(--font-mono));
    }

  }
</style>
