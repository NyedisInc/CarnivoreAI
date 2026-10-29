<script lang="ts">
  import type { LedgerSnapshot } from '../../opscenter/api';
  import { GLANCE_TILE_HEIGHT_PX, GLANCE_TILE_WIDTH_PX } from '../drawer-zone/glance';
  import { declaredGlanceHeight } from '../../opscenter/widgets/glance-declarations';
  import { accountSwitch } from '../account-switch/switch-store.svelte';
  import { openLedgerScreen } from '../ledger/screen-host';
  import { providerGlanceTiles } from './glance-tiles';
  import ProviderGlanceTile from './ProviderGlanceTile.svelte';

  let { snapshot, now }: { snapshot: LedgerSnapshot | null; now: number } = $props();

  const tiles = $derived(providerGlanceTiles(snapshot, now, {}, accountSwitch.data));
  const height = declaredGlanceHeight('core.ledger') ?? GLANCE_TILE_HEIGHT_PX;
</script>

{#if tiles.length > 0}
  <div class="ldp-glance" data-ledger-glance>
    {#each tiles as tile (tile.key)}
      <div class="ldp-glance-tile" style:width={`${GLANCE_TILE_WIDTH_PX}px`} style:height={`${height}px`}>
        <ProviderGlanceTile data={tile.data} onopen={() => openLedgerScreen()} />
      </div>
    {/each}
  </div>
{/if}

<style>
  @layer components {
    .ldp-glance {
      display: flex;
      flex-wrap: wrap;
      gap: var(--oc-space-1);
      margin-top: var(--oc-space-1);
      padding-top: var(--oc-space-2);
      border-top: var(--oc-border) solid var(--oc-line-faint);
    }

    .ldp-glance-tile {
      flex: 0 0 auto;
    }
  }
</style>
