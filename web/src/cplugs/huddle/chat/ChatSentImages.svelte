<script lang="ts">
  import { authFetchBlob } from '../../sdk';
  import TaskManagerThumb from '../TaskManagerThumb.svelte';

  let { sessionId, paths }: { sessionId: string; paths: string[] } = $props();
  const nameOf = (path: string): string => path.slice(path.lastIndexOf('/') + 1);
  const read = (path: string): Promise<Blob> => authFetchBlob(`/sessions/${encodeURIComponent(sessionId)}/upload-image?path=${encodeURIComponent(path)}`);
</script>

<div class="hdc-sent-images" data-chat-sent-images>
  {#each paths as path (path)}
    {#await read(path) then blob}
      <TaskManagerThumb file={blob} name={nameOf(path)} />
    {:catch}
      <span class="hdc-sent-gone">{nameOf(path)}</span>
    {/await}
  {/each}
</div>

<style>
  @layer components {
    .hdc-sent-images { display: flex; flex-wrap: wrap; gap: var(--oc-space-1); margin-top: var(--oc-space-1); }
    .hdc-sent-gone { color: var(--oc-text-dim); overflow-wrap: anywhere; }
  }
</style>
