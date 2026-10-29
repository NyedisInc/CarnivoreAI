
<script lang="ts">
    import { t } from '../i18n/index.svelte';

    let grid = $state<{ cols: number; rows: number } | null>(null);

    export function setGrid(next: { cols: number; rows: number } | null): void {
        grid = next;
    }
</script>

{#if grid}
    <div class="terminal-size-notice" role="status">
        {t('terminal.size.constrained', { cols: grid.cols, rows: grid.rows })}
    </div>
{/if}

<style>
  @layer components {
      .terminal-size-notice {
          position: absolute;
          top: 8px;
          right: 12px;
          z-index: 1100;
          pointer-events: none;

          max-width: calc(100% - 24px);
          box-sizing: border-box;
          padding: 2px var(--oc-space-2);

          background: var(--oc-ground-raised);
          border: 1px solid var(--oc-line-panel);
          border-radius: var(--oc-radius-sm);

          color: var(--oc-text-secondary);
          font-family: var(--font-mono);
          font-size: var(--oc-fs-label);
          line-height: 1.4;
          opacity: 0.85;
          white-space: nowrap;
          overflow: hidden;
          text-overflow: ellipsis;
      }
  }
</style>
