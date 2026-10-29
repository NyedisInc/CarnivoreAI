<script lang="ts">
  import type { ShellView } from '../sidebar-shell/shell.svelte';
  import ZoneTabContext from '../zone-shell/ZoneTabContext.svelte';
  import { rootZone, SESSION_LIST_TAB } from '../drawer-layout/root-zone.svelte';
  import Body from './SessionListBody.svelte';

  let { view }: { view: ShellView } = $props();

  const zone = rootZone();
  const tab = { key: SESSION_LIST_TAB, kind: 'panel' } as const;
</script>

<ZoneTabContext {zone} {tab}>
  <Body {view} />
</ZoneTabContext>
