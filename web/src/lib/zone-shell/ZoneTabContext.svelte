<script lang="ts">
  import { onDestroy, untrack, type Snippet } from 'svelte';
  import { adoptFrameHeader, provideTabPane } from '../../opscenter/shell/frame-header.svelte';
  import { provideZonePane } from './zone-pane';
  import type { Zone } from './zone.svelte';
  import type { TabRef } from './zone-types';

  let { zone, tab, pane = true, children }: { zone: Zone; tab: TabRef; pane?: boolean; children?: Snippet } = $props();

  const key = untrack(() => tab.key);
  const header = untrack(() => zone.headerFor(key));
  adoptFrameHeader(header);
  provideZonePane({
    get tab() {
      return tab;
    },
    header,
    get visible() {
      return zone.visibility(key);
    },
  });
  if (untrack(() => pane)) {
    provideTabPane({
      get active() {
        return zone.spec.active() === key;
      },
      get visible() {
        return zone.visibility(key);
      },
    });
  }

  onDestroy(() => zone.release(key));
</script>

{@render children?.()}
