
<script lang="ts">
    import TerminalFoot from '../../opscenter/cells/terminal-live/TerminalFoot.svelte';

    let sessionId = $state('');
    let width = $state(0);
    let root = $state<HTMLDivElement | null>(null);

    $effect(() => {
        const el = root;
        if (!el) return;
        const measure = (): void => {
            width = el.offsetWidth || 0;
        };
        measure();
        const RO = (globalThis as { ResizeObserver?: typeof ResizeObserver }).ResizeObserver;
        const observer = typeof RO === 'function' ? new RO(measure) : null;
        observer?.observe(el);
        return () => {
            observer?.disconnect();
        };
    });

    export function setSession(id: string): void {
        sessionId = (id ?? '').trim();
    }
</script>

<div class="terminal-foot-host" bind:this={root}>
    {#if sessionId}
        <TerminalFoot {sessionId} {width} />
    {/if}
</div>

<style>
  @layer components {
      .terminal-foot-host {
          display: block;
          min-width: 0;
      }
  }
</style>
