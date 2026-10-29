<script lang="ts">
  import TabStrip from '../shell/TabStrip.svelte';
  import CascadeMenu from '../../lib/drawer-tabs/CascadeMenu.svelte';
  import LiveRegion from '../engine/LiveRegion.svelte';
  import { terminalLayout } from '../engine/layout.svelte';
  import { PRIMARY_SLOT } from '../engine/model';
  import { createTabController } from '../cells/terminal-group/tab-controller.svelte';
  import { t } from '../../lib/i18n/index.svelte';
  import { phoneTabSource } from '../layouts/phone.svelte';

  const ctl = createTabController(() => PRIMARY_SLOT, () => {}, phoneTabSource);
  import Icon from '../ui/Icon.svelte';
  import AlertBell from '../../lib/app-alerts/AlertBell.svelte';
  import TabKey, { keyFace } from '../../lib/zone-shell/TabKey.svelte';

  /* close the agents drawer */
  function toggleDrawer(): void {
    (globalThis as { SessionSidebar?: { toggle: () => void } }).SessionSidebar?.toggle();
  }

  function openMenu(e: Event): void {
    e.stopPropagation();
    document.getElementById('header-menu-toggle')?.click();
  }
</script>

<div
  class="tw:flex tw:min-h-11 tw:min-w-0 tw:items-stretch tw:border-b tw:border-[var(--oc-line-chrome)] tw:bg-[var(--oc-ground-chrome)]"
  data-phone-tabs
>
  <TabKey
    id="claw"
    variant="phone"
    classes="tw:flex tw:min-h-11 tw:w-11 tw:shrink-0 tw:items-center tw:justify-center tw:border-0 tw:bg-transparent tw:p-0"
    face={keyFace({ ariaLabel: t('opscenter.topbar.drawer_open') })}
    iconPx={24}
    quiet
    state={null}
    active={false}
    tabbable
    attrs={{ 'aria-controls': 'session-sidebar-panel', 'data-phone-tabs-claw': '' }}
    onpress={toggleDrawer}
  >
    {#snippet body()}<img
      class="tw:h-6 tw:w-6 tw:object-contain"
      src="/static/img/carnivore/carnivore-mark.png"
      srcset="/static/img/carnivore/carnivore-mark@2x.png 2x"
      alt=""
    />{/snippet}
  </TabKey>
  <div class="tw:flex tw:min-w-0 tw:flex-1" data-phone-tabs-scroll>
  <TabStrip
    touch
    items={ctl.items}
    active={ctl.active}
    onSelect={ctl.select}
    onClose={ctl.close}
    onKill={(tab) => void ctl.kill(tab)}
    newOpen={ctl.newAnchor !== null}
    onNew={(button) => (ctl.newAnchor = ctl.newAnchor ? null : button)}
    onTabMenu={ctl.openTabMenu}
    group={PRIMARY_SLOT}
  />
  </div>
  <div class="tw:flex tw:shrink-0 tw:items-center" data-phone-tabs-end>
    <AlertBell place="drawer" />
    <button
      type="button"
      class="tw:flex tw:min-h-11 tw:w-11 tw:shrink-0 tw:items-center tw:justify-center tw:border-0 tw:bg-transparent tw:p-0 tw:text-[var(--oc-text-dim)]"
      aria-label={t('opscenter.phone.more')}
      aria-haspopup="true"
      data-phone-tabs-kebab
      onclick={openMenu}
    >
      <Icon name="kebab" size={18} />
    </button>
  </div>
</div>
{#if ctl.newAnchor}
  <CascadeMenu root={ctl.menu} anchor={ctl.newAnchor} label={t('opscenter.tabs.new')} onClose={() => (ctl.newAnchor = null)} />
{/if}
{#if ctl.tabMenuAnchor}
  <CascadeMenu root={ctl.tabMenuNodes} anchor={ctl.tabMenuAnchor} label={t('opscenter.tabs.menu_label')} onClose={ctl.closeTabMenu} />
{/if}
<LiveRegion store={terminalLayout} />
