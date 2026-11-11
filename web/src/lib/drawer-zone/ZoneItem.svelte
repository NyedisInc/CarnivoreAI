<script lang="ts">
  import LedgerCell from '../../opscenter/cells/ledger/Cell.svelte';
  import { META } from '../../opscenter/engine/meta';
  import type { WidgetManifest } from '../../opscenter/widgets/types';
  import { drawerZone } from './zone-store.svelte';
  import { lookOf, zoneItemKey, type ZoneItem as Item } from './zone-model';
  import PlacementBody from '../zone-shell/PlacementBody.svelte';
  import ZoneShell from '../zone-shell/ZoneShell.svelte';
  import { untrack } from 'svelte';
  import { drawerCardZone } from './area-zones';

  let { item, manifest }: { item: Item; manifest: WidgetManifest } = $props();

  const key = $derived(zoneItemKey(item));
  const look = $derived(lookOf(manifest, item));

  const compactLedger = $derived(manifest.id === 'core.ledger' && look !== 'full');

  const zone = drawerCardZone(untrack(() => zoneItemKey(item)));
  const tabKey = untrack(() => zoneItemKey(item));
  const watchOnScreen = zone.watch(tabKey);
</script>

<ZoneShell {zone} bare>
  {#snippet tab()}
    <div class="dz-item" data-zone-item={key} data-look={look ?? ''} data-zone-pane={tabKey} data-zone-visible={zone.visibility(tabKey)} {@attach watchOnScreen}>
      {#if compactLedger}
        <LedgerCell drawer width={0} height={0} meta={META.ledger} instance={key} phone={false} limit={null} />
      {:else}
        <PlacementBody host="drawer" source={drawerZone} placementKey={key} {manifest} target={item.target ?? null} view={item.view ?? null} instance={item.instance ?? null} options={item.options} />
      {/if}
    </div>
  {/snippet}
</ZoneShell>

<style>
  @layer components {
    .dz-item {
      min-width: 0;
    }
  }
</style>
