
<script lang="ts">
    import { t } from '../i18n/index.svelte';

    let failed = $state(false);
    let dismissed = $state(false);

    export function setFailed(next: boolean): void {
        failed = next;
        if (next) dismissed = false;
    }

    function dismiss(): void {
        dismissed = true;
    }
</script>

{#if failed && !dismissed}
    <div class="terminal-startup-notice" role="status">
        <span class="terminal-startup-notice__text">{t('terminal.startup.failed')}</span>
        <button
            type="button"
            class="terminal-startup-notice__dismiss"
            onclick={dismiss}
            aria-label={t('terminal.startup.dismiss')}
        >&times;</button>
    </div>
{/if}

<style>
  @layer components {
      .terminal-startup-notice {
          position: absolute;
          top: 15px;
          left: 15px;
          z-index: 1105;

          display: flex;
          align-items: center;
          gap: 10px;
          max-width: min(480px, calc(100% - 30px));
          box-sizing: border-box;
          padding: var(--oc-space-2) 10px;

          background: var(--oc-ground-raised);
          border: 1px solid var(--oc-line-panel);
          border-left: 3px solid var(--oc-coral);
          border-radius: var(--oc-radius-sm);

          color: var(--oc-text-primary);
          font-family: var(--font-mono);
          font-size: 13px;
          line-height: 1.4;
      }

      .terminal-startup-notice__text {
          flex: 1;
          min-width: 0;
      }

      .terminal-startup-notice__dismiss {
          flex: none;
          width: 20px;
          height: 20px;
          display: flex;
          align-items: center;
          justify-content: center;
          border: none;
          background: transparent;
          color: var(--oc-text-secondary);
          font-size: 15px;
          line-height: 1;
          cursor: pointer;
          border-radius: var(--oc-radius-sm);
          opacity: 0.75;
      }

      .terminal-startup-notice__dismiss:hover {
          opacity: 1;
          background: var(--oc-ground-hover);
          color: var(--oc-text-primary);
      }
  }
</style>
