<script lang="ts">
  import { ModalShell } from '../sdk/ui';

  let { url, name, close }: { url: string; name: string; close: (value: null) => void } = $props();
</script>

<ModalShell title={name} onCancel={() => close(null)} width="min(94vw, 1100px)">
  <div class="hdc-preview"><img class="hdc-preview-img" src={url} alt={name} data-task-manager-preview-image /></div>
</ModalShell>

<style>
  @layer components {
    .hdc-preview {
      display: flex;
      justify-content: center;
      max-height: 78vh;
      overflow: auto;
    }

    .hdc-preview-img {
      display: block;
      max-width: 100%;
      height: auto;
      object-fit: contain;
    }
  }
</style>
