<script lang="ts">
  import { openModal, t } from '../sdk';
  import ImagePreview from './TaskManagerImagePreview.svelte';

  let { file, name }: { file: Blob; name: string } = $props();
  let url = $state('');

  $effect(() => {
    const made = URL.createObjectURL(file);
    url = made;
    return () => URL.revokeObjectURL(made);
  });
</script>

{#if url}
  <button type="button" class="hdc-thumb" data-base-exempt="a picture-only thumbnail with no text label for the base look to wrap" data-task-manager-thumb aria-label={t('cplug.huddle.files.preview', { name })}
          onclick={() => void openModal<null, Record<string, unknown>>(ImagePreview as never, { url, name })}>
    <img src={url} alt="" />
  </button>
{/if}

<style>
  @layer components {
    .hdc-thumb {
      flex: none;
      width: var(--oc-space-5);
      height: var(--oc-space-5);
      padding: 0;
      border: 1px solid var(--oc-control-line);
      border-radius: var(--oc-radius-sm);
      background: var(--oc-ground-raised);
      cursor: zoom-in;
      overflow: hidden;
    }

    .hdc-thumb img {
      display: block;
      width: 100%;
      height: 100%;
      object-fit: cover;
    }
  }
</style>
