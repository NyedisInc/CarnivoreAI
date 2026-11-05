<script lang="ts">
  let { status }: { status: { text: string; tone: 'muted' | 'error' } | null } = $props();
</script>

<p class="files-status" class:files-status--error={status?.tone === 'error'} role="status" aria-live="polite" hidden={!status}>
  {status?.text ?? ''}
</p>

<style>
  @layer components {
    .files-status {
      flex: 0 0 auto;
      margin: 0;
      padding: var(--oc-space-0-5) var(--oc-space-2);
      font-size: var(--oc-fs-label);
      color: var(--oc-text-secondary);
      box-shadow: inset 0 1px 0 0 var(--oc-line-faint);
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }

    .files-status[hidden] {
      display: none;
    }

    .files-status--error {
      color: var(--oc-coral);
    }
  }
</style>
