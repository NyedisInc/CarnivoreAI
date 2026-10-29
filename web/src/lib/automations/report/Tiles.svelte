
<script lang="ts">
  import { StatTile } from '../../base';
  import type { Tile } from '../logic/report-rules';

  let { tiles }: { tiles: Tile[] } = $props();
</script>

{#if tiles.length}
  <div class="r-tiles">
    {#each tiles as tile (tile.key)}
      <div class="r-tile" data-key={tile.key} data-change={tile.change}>
        <StatTile label={tile.label} figure={tile.text} sub={tile.changeText} />
      </div>
    {/each}
  </div>
{/if}
