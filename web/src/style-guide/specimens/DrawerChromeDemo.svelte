<script lang="ts">
  import { onMount } from 'svelte';
  import DrawerHeader from '../../lib/drawer/DrawerHeader.svelte';
  import DrawerStats from '../../lib/drawer-tabs/DrawerStats.svelte';
  import SidebarControls from '../../lib/sidebar-widgets/SidebarControls.svelte';
  import { mountPanel } from '../../lib/mount';
  import { publishFloorRows } from '../../lib/drawer/floor-feed.svelte';
  import type { FeedBody } from '../../lib/stats-feed/types';

  let { part = 'header' }: { part?: 'header' | 'stats' } = $props();

  const NOW = 1_791_695_055;
  const OUT = [10, 40, 25, 60, null, 0, 35, 80, 55, 30, 45, 70, 20, 50, 65, 40];
  const IN = [100, 300, 220, 500, null, 0, 280, 700, 480, 260, 400, 640, 180, 450, 600, 350];
  const body = (state: string): FeedBody => ({
    v: 1, rev: 1, window: '1h', bucket_seconds: 60, start: NOW - 16 * 60, now: NOW, state,
    in: state === 'stats_off' ? OUT.map(() => null) : IN, out: state === 'stats_off' ? OUT.map(() => null) : OUT, totals: null,
    rate: state === 'stats_off' ? null : { span_seconds: 280, fresh: 2400, cache_write: 900, cache_read: 3500, out: 113 },
    sources: [{ host_key: 'local', label: 'this computer', state }],
  });

  publishFloorRows([
    { name: 'a', status: 'working' }, { name: 'b', status: 'idle', unread: true }, { name: 'c', status: 'working_subagent' },
    { name: 'd', status: 'idle' }, { name: 'e', status: 'idle', unread: true },
  ] as never);

  onMount(() => {
    if (part === 'header') mountPanel('session-sidebar-topbar-controls', SidebarControls as never);
  });
</script>

{#if part === 'header'}
  <div class="sg-drawer-host"><div id="session-sidebar-header" class="session-sidebar-header"><DrawerHeader /></div></div>
{:else}
  <div class="sg-grid-2">
    <div class="sg-drawer-host"><DrawerStats feed={body('ok')} /></div>
    <div class="sg-drawer-host sg-drawer-host--narrow"><DrawerStats feed={body('ok')} /></div>
    <div class="sg-drawer-host"><DrawerStats feed={body('stats_off')} /></div>
  </div>
{/if}
