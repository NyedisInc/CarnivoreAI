<script lang="ts">
  import GridSurface from '../../opscenter/engine/GridSurface.svelte';
  import CellHost from '../../opscenter/CellHost.svelte';
  import LiveRegion from '../../opscenter/engine/LiveRegion.svelte';
  import EmptySpaceMenu from '../../opscenter/layout-editor/EmptySpaceMenu.svelte';
  import { warroomLayout } from '../../opscenter/engine/layout.svelte';
  import { GUTTER } from '../../opscenter/engine/tracks';
  import { watchStillness, watchViewport } from '../../opscenter/engine/viewport.svelte';
  import { installFlushOnExit } from '../../opscenter/engine/persist';

  $effect(() => watchViewport());
  $effect(() => watchStillness());
  $effect(() => installFlushOnExit());
</script>

<GridSurface gutter={GUTTER} store={warroomLayout} sizeKey="surface:warroom">
  {#snippet renderCell(slot)}
    <CellHost id={slot.id} store={warroomLayout} />
  {/snippet}
</GridSurface>
<EmptySpaceMenu surface="warroom" />
<LiveRegion store={warroomLayout} />
