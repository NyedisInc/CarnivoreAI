<script lang="ts">
  import type { Component } from 'svelte';

  const { body, tabId }: { body: Component; tabId?: string } = $props();
  const Body = $derived(body as Component<{ tabId?: string }>);
</script>

<div class="oc-page" data-plugin-main-view><Body {tabId} /></div>
