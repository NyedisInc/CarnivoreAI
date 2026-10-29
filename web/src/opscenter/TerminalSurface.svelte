<script lang="ts">
  import GridSurface from './engine/GridSurface.svelte';
  import { GUTTER } from './engine/tracks';
  import CellHost from './CellHost.svelte';
  import LiveRegion from './engine/LiveRegion.svelte';
  import { terminalLayout } from './engine/layout.svelte';
  import { watchStillness, watchViewport } from './engine/viewport.svelte';
  import { installFlushOnExit } from './engine/persist';
  import { watchZoomKeys } from './engine/layout-zoom.svelte';
  import EmptySpaceMenu from './layout-editor/EmptySpaceMenu.svelte';
  import SessionRail from '../lib/session-rail/SessionRail.svelte';

  $effect(() => watchViewport());
  $effect(() => watchStillness());
  $effect(() => installFlushOnExit());
  $effect(() => watchZoomKeys());
</script>

<GridSurface gutter={GUTTER} store={terminalLayout}>
  {#snippet renderCell(slot)}
    <CellHost id={slot.id} store={terminalLayout} />
  {/snippet}
</GridSurface>

<SessionRail edge="bottom" />

<SessionRail edge="side" />

<EmptySpaceMenu surface="terminal" />
<LiveRegion store={terminalLayout} />
