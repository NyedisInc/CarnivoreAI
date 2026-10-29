<script lang="ts">
  import ZoneShell from '../ZoneShell.svelte';
  import ZoneToolbar from '../ZoneToolbar.svelte';
  import StubTab from './StubTab.svelte';
  import { worldZone } from './world.svelte';
  import type { TabRef } from '../zone-types';

  let { mode = 'all' }: { mode?: 'all' | 'active' } = $props();
  const zone = worldZone();
</script>

<ZoneToolbar {zone} />
<ZoneShell {zone} mount={mode} tab={stub} />

{#snippet stub(tab: TabRef)}
  <StubTab name={tab.key} />
{/snippet}
