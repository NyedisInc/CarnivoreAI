
<script lang="ts">
  let { hostKey = null, label = null, state = 'up' }: { hostKey?: string | null; label?: string | null; state?: string | null } = $props();
  const text = $derived(label || hostKey || '');
</script>

{#if hostKey && hostKey !== 'local' && text}<span class="oc-machine-badge" data-machine-badge data-host-state={state && state !== 'up' ? state : undefined} title={text}>{text}</span>{/if}

<style>
  @layer components {
    .oc-machine-badge {
      display: inline-block;
      flex: none;
      max-width: 9em;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
      margin-left: var(--oc-space-1);
      padding: 0 var(--oc-space-1);
      border: 1px solid var(--oc-line-frame);
      border-radius: 2px;
      color: var(--oc-text-secondary);
      font-family: var(--font-mono);
      font-size: var(--oc-fs-micro);
      line-height: 14px;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      vertical-align: middle;
    }
    .oc-machine-badge[data-host-state] {
      opacity: 0.6;
    }
  }
</style>
