<script lang="ts">
  import type { Component } from 'svelte';

  const { body: Body }: { body: Component } = $props();
</script>

<div class="oc-page" data-plugin-main-view><Body /></div>
