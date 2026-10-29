<!-- running sessions -->
<script lang="ts">
    import { t } from '../i18n/index.svelte';
    import { newSession } from '../../opscenter/api/host';

    const CARNIVORE_BACKGROUND = '/static/css/themes/carnivore/background.webp';

    function openDrawer(): void {
        const sidebar = (globalThis as { SessionSidebar?: { open?: () => void } }).SessionSidebar;
        if (typeof sidebar?.open !== 'function') {
            console.error('CloudeWeb: window.SessionSidebar.open is not available, the drawer did not open');
            return;
        }
        sidebar.open();
    }
</script>

<div class="terminal-empty" role="region" aria-label={t('terminal.empty.title')}>
    <img class="terminal-empty__art" src={CARNIVORE_BACKGROUND} alt="" aria-hidden="true" />
    <div class="terminal-empty__card">
        <h2 class="terminal-empty__title">{t('terminal.empty.title')}</h2>
        <p class="terminal-empty__body">{t('terminal.empty.body')}</p>
        <div class="terminal-empty__actions">
            <button type="button" class="oc-btn terminal-empty__btn--drawer" onclick={openDrawer}>
                {t('terminal.empty.open_drawer')}
            </button>
            <button type="button" class="oc-btn oc-btn--confirm terminal-empty__btn--new" onclick={() => void newSession(null)}>
                {t('terminal.empty.new_session')}
            </button>
        </div>
    </div>
</div>

<style>
  @layer components {
      .terminal-empty {
          position: absolute;
          inset: 0;
          z-index: 20;
          display: flex;
          align-items: center;
          justify-content: center;
          padding: var(--oc-space-4);
          box-sizing: border-box;
          overflow: hidden;
          background: var(--oc-ground-page);
      }

      .terminal-empty__art {
          position: absolute;
          inset: 0;
          width: 100%;
          height: 100%;
          object-fit: cover;
          pointer-events: none;
      }

      .terminal-empty__card {
          position: relative;
          max-width: min(420px, 100%);
          box-sizing: border-box;
          padding: 20px 22px;
          background: var(--oc-ground-raised);
          border: 1px solid var(--oc-line-panel);
          border-radius: var(--oc-radius-sm);
          color: var(--oc-text-primary);
          font-family: var(--font-mono);
          text-align: center;
      }

      .terminal-empty__title {
          margin: 0 0 var(--oc-space-2);
          font-size: 15px;
          font-weight: 600;
          color: var(--oc-text-bright);
      }

      .terminal-empty__body {
          margin: 0 0 var(--oc-space-4);
          font-size: 13px;
          line-height: 1.5;
          color: var(--oc-text-secondary);
      }

      .terminal-empty__actions {
          display: flex;
          flex-wrap: wrap;
          gap: 10px;
          justify-content: center;
      }
  }
</style>
