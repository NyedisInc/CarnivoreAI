<script lang="ts">
  import AbsSurface from './engine/rects/AbsSurface.svelte';
  import { GUTTER } from './engine/tracks';
  import CellHost from './CellHost.svelte';
  import LiveRegion from './engine/LiveRegion.svelte';
  import { terminalLayout } from './engine/layout.svelte';
  import { watchStillness, watchViewport } from './engine/viewport.svelte';
  import { installFlushOnExit } from './engine/persist';
  import { watchZoomKeys } from './engine/layout-zoom.svelte';
  import EmptySpaceMenu from './layout-editor/EmptySpaceMenu.svelte';
  import SessionRail from '../lib/session-rail/SessionRail.svelte';
  import { componentMerge } from './engine/tab-drag';
  import { kindOf } from './engine/meta';
  import type { SlotId } from './engine/types';

  function mergeFor(id: SlotId) {
    return kindOf(id) === 'terminal' ? componentMerge(id) : undefined;
  }

  $effect(() => watchViewport());
  $effect(() => watchStillness());
  $effect(() => installFlushOnExit());
  $effect(() => watchZoomKeys());
</script>

<AbsSurface gutter={GUTTER} store={terminalLayout} dropId="terminal" merge={mergeFor}>
  {#snippet renderCell(slot)}
    <CellHost id={slot.id} store={terminalLayout} />
  {/snippet}
</AbsSurface>

<SessionRail edge="bottom" />

<SessionRail edge="side" />

<EmptySpaceMenu surface="terminal" />
<LiveRegion store={terminalLayout} />
