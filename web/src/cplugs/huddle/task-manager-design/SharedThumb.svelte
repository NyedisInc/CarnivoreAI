<script lang="ts">
  import { Icon } from '../../sdk/ui';
  import { fetchFileBlob } from '../task-manager-files-api';

  let { itemId, fileId }: { itemId: number; fileId: string } = $props();

  let url = $state('');

  $effect(() => {
    let live = true;
    let made = '';
    fetchFileBlob(itemId, fileId).then(
      (blob) => { if (live) url = made = URL.createObjectURL(blob); },
      () => {},
    );
    return () => {
      live = false;
      if (made) URL.revokeObjectURL(made);
      url = '';
    };
  });
</script>

{#if url}<img src={url} alt="" class="tm-thumbnail" />{:else}<Icon name="image" size={16} />{/if}
