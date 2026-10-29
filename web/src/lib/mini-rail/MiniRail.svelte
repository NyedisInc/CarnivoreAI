<script lang="ts">
  import SidebarRail from '../sidebar-widgets/SidebarRail.svelte';
  import AlertBell from '../app-alerts/AlertBell.svelte';
  import TabKey, { keyFace } from '../zone-shell/TabKey.svelte';
  import Icon from '../../opscenter/ui/Icon.svelte';
  import { t } from '../i18n/index.svelte';
  import RailMenu from '../sidebar-widgets/RailMenu.svelte';
  import { onRailShellMenuKey } from '../sidebar-widgets/rail-menu.svelte';

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
    (globalThis as { SessionSidebar?: { open?: () => void } }).SessionSidebar?.open?.();
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
    <AlertBell place="rail" />
    <SidebarRail pin={reopen} pinName={t('drawer.rail.open')} stats />
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
      z-index: 1100;
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
  }
</style>
