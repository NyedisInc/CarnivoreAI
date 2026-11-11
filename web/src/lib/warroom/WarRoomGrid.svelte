<script lang="ts">
  import AbsSurface from '../../opscenter/engine/rects/AbsSurface.svelte';
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

<AbsSurface gutter={GUTTER} store={warroomLayout} sizeKey="surface:warroom" dropId="warroom">
  {#snippet renderCell(slot)}
    <CellHost id={slot.id} store={warroomLayout} />
  {/snippet}
</AbsSurface>
<EmptySpaceMenu surface="warroom" />
<LiveRegion store={warroomLayout} />
