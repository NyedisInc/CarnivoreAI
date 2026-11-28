<script lang="ts">
  import type { Snippet } from 'svelte';
  import TaskManagerChips from '../../TaskManagerChips.svelte';
  import { carriesFiles, filesOf } from '../../task-manager-files';
  import type { Attachments } from '../ask-state.svelte';

  let { box, id, children }: { box: Attachments; id: string; children: Snippet } = $props();

  function onPaste(event: ClipboardEvent): void {
    const files = filesOf(event.clipboardData);
    if (files.length === 0) return;
    event.preventDefault();
    box.add(files);
  }

  function onDragOver(event: DragEvent): void {
    if (carriesFiles(event.dataTransfer)) event.preventDefault();
  }

  function onDrop(event: DragEvent): void {
    const files = filesOf(event.dataTransfer);
    if (files.length === 0) return;
    event.preventDefault();
    box.add(files);
  }
</script>

<div class="hdq-paste" data-ask-paste={id} onpaste={onPaste} ondragover={onDragOver} ondrop={onDrop} role="group">
  {@render children()}
  {#if box.chips.length}<TaskManagerChips chips={box.chips} onRemove={box.remove} />{/if}
</div>

<style>
  @layer components {
    .hdq-paste {
      display: flex;
      flex-direction: column;
      gap: var(--oc-space-1);
      min-width: 0;
    }
  }
</style>
