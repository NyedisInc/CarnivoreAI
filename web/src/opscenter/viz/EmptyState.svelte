<script lang="ts">

  let { line }: { line: string } = $props();

</script>

<p class="viz-empty" role="status">{line}</p>

<style>
  @layer components {
    .viz-empty { max-width: 44ch; margin: var(--oc-space-2) 0; color: var(--oc-text-muted); font: var(--oc-fs-label)/1.5 var(--font-mono); letter-spacing: .01em; text-wrap: pretty; }
  }
</style>
