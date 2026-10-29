<script lang="ts">
  const { text }: { text: string } = $props();
</script>

<p class="pkg-refusal" data-swarm-refusal role="status">{text}</p>

<style>
  @layer components {
    .pkg-refusal {
      margin: 0;
      padding: var(--oc-space-1) 0;
      color: var(--oc-coral);
      font-family: var(--font-mono);
      font-size: var(--oc-fs-label);
    }
  }
</style>
