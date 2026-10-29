<script lang="ts">
  /* the home screen */
  import Icon from '../ui/Icon.svelte';
  import { isDemo, transport } from '../api';
  import { t } from '../../lib/i18n/index.svelte';
  import { viewport } from '../engine/viewport.svelte';
  import AlertBell from '../../lib/app-alerts/AlertBell.svelte';
  import TabKey, { keyFace } from '../../lib/zone-shell/TabKey.svelte';
  import { dashboardFromSearch } from '../../popout/popout';
  import { homeBoards } from '../engine/home-sync.svelte';
  import PopoutBarActions from './PopoutBarActions.svelte';
  import { accountChip, toggleAccountMenu } from '../../lib/drawer-hud/account-menu.svelte';
  import { avatarHtml } from '../../lib/drawer/avatar';
  import { openSignInDoor } from '../../lib/carnivore-account/sign-in-door';

  const member = $derived(accountChip.identity?.kind === 'member');
  const accountName = $derived(member ? (accountChip.identity?.name ?? '') : t('drawer.account.lurker'));

  let { popout = false }: { popout?: boolean } = $props();

  const popoutBoard = popout && typeof window !== 'undefined' ? dashboardFromSearch(window.location.search) : null;
  const popoutBoardName = $derived(popoutBoard ? (homeBoards.list.find((one) => one.id === popoutBoard)?.name ?? '') : '');

  let agentsDrawerOpen = $state(false);

  $effect(() => {
    const panel = document.getElementById('session-sidebar-panel');
    if (!panel) return;
    const read = (): void => {
      agentsDrawerOpen = panel.classList.contains('session-sidebar-panel--open');
    };
    read();
    const observer = new MutationObserver(read);
    observer.observe(panel, { attributes: true, attributeFilter: ['class'] });
    return () => observer.disconnect();
  });

  function sidebar(): { open: () => void; toggle: () => void } | null {
    return (globalThis as { SessionSidebar?: { open: () => void; toggle: () => void } }).SessionSidebar ?? null;
  }

  const CONNECTION_KEYS: Readonly<Record<string, string>> = {
    connected: 'opscenter.topbar.connection.connected',
    disconnected: 'opscenter.topbar.connection.disconnected',
    unknown: 'opscenter.topbar.connection.unknown',
  };

  const connection = $derived(
    t(CONNECTION_KEYS[transport.state] ?? 'opscenter.topbar.connection.unknown'),
  );

  const connectionLabel = $derived(
    t('opscenter.topbar.connection.title', { state: connection }),
  );
</script>

<header class="oc-topbar" class:oc-topbar--popout={popout}>
  
  {#if !popout}
  <TabKey
    id="drawer"
    variant="topbar"
    classes="oc-topbar-drawer"
    face={keyFace({ ariaLabel: t('opscenter.topbar.drawer_open'), tip: t('opscenter.topbar.drawer_open') })}
    iconPx={18}
    quiet
    state={null}
    active={false}
    tabbable
    onpress={() => sidebar()?.open()}
  >
    {#snippet body()}<Icon name="hamburger" size={18} strokeWidth={2} />{/snippet}
  </TabKey>
  {/if}

  
  {#if viewport.phone && !popout}
    <TabKey
      id="brand"
      variant="topbar"
      classes="oc-topbar-brand"
      face={keyFace({ ariaLabel: t(agentsDrawerOpen ? 'opscenter.topbar.drawer_close' : 'opscenter.topbar.drawer_open') })}
      iconPx={20}
      quiet
      state="expanded"
      active={agentsDrawerOpen}
      tabbable
      attrs={{ 'aria-controls': 'session-sidebar-panel' }}
      onpress={() => sidebar()?.toggle()}
    >
      {#snippet body()}<img
        class="oc-topbar-word"
        src="/static/img/carnivore/carnivore-wordmark.png"
        srcset="/static/img/carnivore/carnivore-wordmark@2x.png 2x"
        alt=""
      />{/snippet}
    </TabKey>
  {:else}
    <img
      class="oc-topbar-word"
      src="/static/img/carnivore/carnivore-wordmark.png"
      srcset="/static/img/carnivore/carnivore-wordmark@2x.png 2x"
      alt={t('opscenter.brand.wordmark_alt')}
    />
  {/if}
  {#if popout}<span class="oc-topbar-title" data-popout-title>{popoutBoardName ? t('opscenter.popout.dashboard_title', { name: popoutBoardName }) : t('opscenter.popout.title')}</span>{/if}
  {#if isDemo()}<span class="oc-topbar-chip oc-topbar-demo">{t('opscenter.topbar.demo')}</span>{/if}

  
  
  {#if !viewport.phone}
  <span class="oc-topbar-conn" title={connectionLabel}>
    <span
      class="oc-topbar-dot"
      data-transport={transport.state}
      role="img"
      aria-label={connectionLabel}
    ></span>
    <span class="oc-topbar-connword">{connection}</span>
  </span>
  {/if}
  <span class="oc-topbar-spacer"></span>
  
  {#if !popout}
    <AlertBell place="drawer" />
    
    <button
      type="button"
      class="session-sidebar-bar__account"
      aria-haspopup="menu"
      aria-expanded="false"
      aria-label={t('drawer.account.chip', { name: accountName })}
      onclick={(e) => toggleAccountMenu(e.currentTarget)}
    >{@html avatarHtml(accountChip.identity)}</button>
    {#if !member}
      <button type="button" class="session-sidebar-bar__signin" onclick={() => openSignInDoor('topbar')}>
        {t('account.chip.signin')}
      </button>
    {/if}
  {/if}
  
  {#if popout}<PopoutBarActions />{/if}
</header>

<style>
  @layer components {
    .oc-topbar {
      display: flex;
      align-items: center;
      height: var(--oc-topbar);
      padding: 0 var(--oc-space-4) 0 22px;
      background: var(--oc-ground-chrome);
      box-shadow: inset 0 -1px 0 0 var(--oc-line-frame);
      white-space: nowrap;
    }

    :global(html[data-desktop-chrome]) .oc-topbar--popout {
      padding-left: max(var(--oc-space-5), var(--desktop-inset-left, 0px));
      -webkit-app-region: drag;
    }

    :global(html[data-desktop-chrome]) .oc-topbar--popout :global(:is(button, a, input, select, textarea, [role='button'], [tabindex])) {
      -webkit-app-region: no-drag;
    }

    .oc-topbar-word {
      display: block;
      height: 20px;
      width: auto;
      margin-right: 9px;
      flex: 0 0 auto;
    }

    .oc-topbar-title {
      margin-right: var(--oc-space-3);
      font-size: var(--oc-fs-label);
      letter-spacing: var(--oc-tracking-title);
      text-transform: uppercase;
      color: var(--oc-orange);
    }

    :global(body.session-sidebar-railed) .oc-topbar-word {
      visibility: hidden;
    }

    :global(body:has(.session-sidebar-panel--open)) .oc-topbar-word {
      visibility: hidden;
    }

    :global(body:not(:has(.session-sidebar-panel--open))) .oc-topbar-word {
      content: url('/static/img/carnivore/carnivore-mark@2x.png');
      width: 30px;
      height: 30px;
    }

    .oc-topbar-chip {
      margin-left: 18px;
      padding: 3px var(--oc-space-2);
      border: var(--oc-border) solid var(--oc-line-panel);
      border-radius: var(--oc-radius-sm);
      font-size: var(--oc-fs-micro);
      color: var(--oc-text-secondary);
    }

    .oc-topbar-conn {
      display: inline-flex;
      align-items: center;
      gap: var(--oc-space-2);
      margin-left: var(--oc-space-2);
      font-size: var(--oc-fs-label);
      color: var(--oc-text-status);
    }

    .oc-topbar-spacer {
      flex: 1 1 auto;
      min-width: var(--oc-space-2);
    }

    .oc-topbar-dot {
      width: 7px;
      height: 7px;
      border-radius: 50%;
      background: var(--oc-text-secondary);
    }

    .oc-topbar-dot[data-transport='connected'] {
      background: var(--oc-green-bright);
    }

    .oc-topbar-dot[data-transport='disconnected'] {
      background: var(--oc-coral);
    }

    .oc-topbar-demo {
      margin-left: var(--oc-space-2);
      color: var(--oc-yellow);
    }

    @media (max-width: 1023px) {
      .oc-topbar {
        position: sticky;
        top: 0;
        z-index: 50;
        padding: 0 var(--oc-space-2);
      }

      .oc-topbar-word {
        height: 18px;
      }

      .oc-topbar-chip {
        display: none;
      }

      .oc-topbar-connword {
        position: absolute;
        width: 1px;
        height: 1px;
        margin: -1px;
        padding: 0;
        overflow: hidden;
        clip-path: inset(50%);
        white-space: nowrap;
        border: 0;
      }
  }

    @media (max-width: 639px) {
      .oc-topbar-word {
        flex: 0 0 auto;
      }
  }
  }
</style>
