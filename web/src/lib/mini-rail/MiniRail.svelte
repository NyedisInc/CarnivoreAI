<script lang="ts">
  import SidebarRail from '../sidebar-widgets/SidebarRail.svelte';
  import { sessionSidebar, type SidebarPick } from '../legacy-globals';
  import AlertBell from '../app-alerts/AlertBell.svelte';
  import TabKey, { keyFace } from '../zone-shell/TabKey.svelte';
  import Icon from '../../opscenter/ui/Icon.svelte';
  import { t } from '../i18n/index.svelte';
  import RailMenu from '../sidebar-widgets/RailMenu.svelte';
  import { onRailShellMenuKey } from '../sidebar-widgets/rail-menu.svelte';
  import { RAIL_RUN } from '../../opscenter/shell/rail-items';
  import { closeDrawerAfterSwitch } from '../drawer-tabs/menu-hotkeys';

  const RAIL_CLASS = 'session-sidebar-railed';

  let railed = $state(false);

  $effect(() => {
    const read = (): void => {
      railed = document.body.classList.contains(RAIL_CLASS);
    };
    read();
    const observer = new MutationObserver(read);
    observer.observe(document.body, { attributes: true, attributeFilter: ['class'] });
    return () => observer.disconnect();
  });

  function openDrawer(): void {
    sessionSidebar<SidebarPick<'open'>>()?.open();
  }

  function openDashboard(): void {
    RAIL_RUN.dashboards?.();
    closeDrawerAfterSwitch();
  }
</script>

{#snippet reopen()}
  <TabKey id="drawer-open" variant="mini" face={keyFace({ ariaLabel: t('drawer.rail.open'), tip: t('drawer.rail.open') })} iconPx={16}
          quiet state={null} active={false} tabbable attrs={{ 'data-rail': 'open', 'aria-controls': 'session-sidebar-panel' }} onpress={openDrawer}>
    {#snippet body()}<Icon name="hamburger" size={16} strokeWidth={2} />{/snippet}
  </TabKey>
{/snippet}


<div class="mr" data-tooltip-side="right" role="presentation" onkeydown={onRailShellMenuKey}>
  {#if railed}
    <div class="mr-head">
      <TabKey id="claw" variant="mini" classes="mr-claw" face={keyFace({ ariaLabel: t('opscenter.nav.dashboards'), tip: t('opscenter.nav.dashboards') })} iconPx={16}
              quiet state={null} active={false} tabbable attrs={{ 'data-rail': 'claw' }} onpress={openDashboard}>
        {#snippet body()}<img src="/static/img/carnivore/carnivore-mark.png" srcset="/static/img/carnivore/carnivore-mark@2x.png 2x" alt="" />{/snippet}
      </TabKey>
      {@render reopen()}
      <AlertBell place="rail" />
    </div>
    <SidebarRail stats />
  {/if}
</div>
<RailMenu closed />

<style>
  @layer components {
    .mr {
      position: fixed;
      top: var(--desktop-inset-top, 0px);
      left: 0;
      bottom: 0;
      z-index: var(--oc-z-drawer);
      width: var(--sidebar-rail-w, 48px);
      box-sizing: border-box;
      display: flex;
      flex-direction: column;
      align-items: stretch;
      background: var(--oc-ground-chrome);
      border-right: var(--oc-border) solid var(--oc-line-chrome);
      font-family: var(--font-mono);
      overflow: hidden;
    }

    .mr-head {
      flex: 0 0 auto;
      display: flex;
      flex-direction: column;
      align-items: center;
      padding-top: var(--oc-space-1);
    }

    :global(.mr-claw) {
      margin-bottom: var(--oc-space-2);
    }

    :global(.mr-claw) img {
      display: block;
      width: 26px;
      height: 26px;
      opacity: 0.85;
    }

    :global(.mr-claw:hover) img,
    :global(.mr-claw:focus-visible) img {
      opacity: 1;
    }

    .mr > :global(.sbr-rail) {
      flex: 1 1 0;
      min-height: 0;
      height: auto;
    }

    .mr :global(.sbr-rail__head) {
      display: none;
    }
  }
</style>
