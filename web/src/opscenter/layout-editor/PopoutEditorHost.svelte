<script lang="ts">
  import { untrack } from 'svelte';
  import { homeBoards } from '../engine/home-sync.svelte';
  import { editingStore, enterLayoutEditor, layoutEditor } from './editor.svelte';
  import LayoutEditorHost from './LayoutEditorHost.svelte';
  import WidgetDrawer from './WidgetDrawer.svelte';

  let { editNow = false }: { editNow?: boolean } = $props();

  const store = $derived(layoutEditor.active ? editingStore() : null);

  let entered = false;
  $effect(() => {
    if (!editNow || entered || !homeBoards.ready) return;
    entered = true;
    untrack(() => enterLayoutEditor());
  });
</script>

<LayoutEditorHost />
{#if layoutEditor.active && store && layoutEditor.page}
  <WidgetDrawer {store} page={layoutEditor.page} />
{/if}
