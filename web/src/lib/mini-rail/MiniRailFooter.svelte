<script lang="ts">
  /* cannot fork */
  import { t } from '../i18n/index.svelte';
  import { reanchorAccountMenu } from '../drawer-hud/account-menu.svelte';

  let { railed }: { railed: boolean } = $props();

  const BAR_SLOT_ID = 'session-sidebar-bar-slot';
  let footerEl = $state<HTMLElement | null>(null);

  // cannot fork
  $effect(() => {
    if (!railed || !footerEl) return;
    const src = document.getElementById(BAR_SLOT_ID);
    if (!src) return;
    const sync = (): void => {
      if (footerEl && src.innerHTML !== footerEl.innerHTML) {
        footerEl.innerHTML = src.innerHTML;
        reanchorAccountMenu();
      }
    };
    sync();
    const observer = new MutationObserver(sync);
    observer.observe(src, { childList: true, subtree: true, attributes: true });
    return () => observer.disconnect();
  });

  function onFooterClick(event: MouseEvent): void {
    const target = event.target as Element | null;
    const btn = target && target.closest ? target.closest('[data-bar-action]') : null;
    if (!btn) return;
    (globalThis as { SessionSidebarBar?: { run?: (action: string | null, el: Element | null) => void } })
      .SessionSidebarBar?.run?.(btn.getAttribute('data-bar-action'), btn);
  }
</script>

<!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_noninteractive_element_interactions -->
  <!-- <button> -->
  <div class="mr-footer" role="group" aria-label={t('drawer.rail.footer')} bind:this={footerEl} onclick={onFooterClick}></div>

<style>
  @layer components {
    /* the account chip */
    .mr-footer {
      flex: 0 0 auto;
      width: 100%;
      padding-top: 6px;
      box-shadow: 0 -1px 0 var(--oc-line-panel);
    }

    :global(.mr-footer .session-sidebar-bar) {
      display: flex;
      flex-direction: column;
      align-items: center;
      gap: 2px;
      padding: 0;
      border-top: 0;
    }

    :global(.mr-footer .session-sidebar-bar__group) {
      flex: 0 0 auto;
      flex-direction: column;
      justify-content: center;
    }

    :global(.mr-footer .session-sidebar-bar__account) {
      padding: 0;
    }

    :global(.mr-footer .session-sidebar-bar__account-name),
    :global(.mr-footer .session-sidebar-bar__account-chevron) {
      display: none;
    }

    :global(.mr-footer .session-sidebar-bar__version) {
      flex: 0 0 auto;
      flex-direction: column;
      gap: 3px;
      max-width: 40px;
      margin-left: 0;
      font-size: 9px;
    }
  }
</style>
