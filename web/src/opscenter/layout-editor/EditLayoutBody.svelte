<script lang="ts">
  import { editingStore, layoutEditor } from './editor.svelte';
  import WidgetDrawer from './WidgetDrawer.svelte';

  const store = $derived(layoutEditor.active ? editingStore() : null);
</script>

{#if layoutEditor.active && store && layoutEditor.page}
  <WidgetDrawer {store} page={layoutEditor.page} docked />
{/if}
