<script lang="ts">
  import TabStrip from '../shell/TabStrip.svelte';
  import { raiseFlag } from '../../lib/page-flags/page-flags';
  import CascadeMenu from '../../lib/drawer-tabs/CascadeMenu.svelte';
  import LiveRegion from '../engine/LiveRegion.svelte';
  import { terminalLayout } from '../engine/layout.svelte';
  import { PRIMARY_SLOT } from '../engine/model';
  import { createTabController } from '../cells/terminal-group/tab-controller.svelte';
  import { t } from '../../lib/i18n/index.svelte';
  import { phoneTabSource } from '../layouts/phone.svelte';
  import TerminalUtilities from '../cells/terminal-live/TerminalUtilities.svelte';
  import { registerTerminalActions } from '../cells/terminal-live/actions';
  import { sessions } from '../api';
  import { primarySessionId } from '../api/host';
  import { rowFor, sessionIdOf } from '../cells/terminal-viewer/meta';
  import { PRIMARY_BIND_EVENT } from '../engine/primary-bind';
  import { overlayClient } from './overlay-client.svelte';

  const ctl = createTabController(() => PRIMARY_SLOT, () => {}, phoneTabSource);
  import AlertBell from '../../lib/app-alerts/AlertBell.svelte';
  import TabKey, { keyFace } from '../../lib/zone-shell/TabKey.svelte';

  /* close the agents drawer */
  function toggleDrawer(): void {
    (globalThis as { SessionSidebar?: { toggle: () => void } }).SessionSidebar?.toggle();
  }

  const pageController = (): unknown => (globalThis as { TerminalController?: unknown }).TerminalController;

  $effect(() => {
    const controller = pageController() as Parameters<typeof registerTerminalActions>[1] | undefined;
    const container = document.getElementById('terminal-container');
    return controller && container ? registerTerminalActions(PRIMARY_SLOT, controller, container, true) : undefined;
  });

  const active = $derived(phoneTabSource.active());
  let boundSession = $state('');
  $effect(() => {
    boundSession = primarySessionId();
    const onBind = (event: Event): void => {
      const id = (event as CustomEvent<{ sessionId?: string }>).detail?.sessionId;
      if (id) boundSession = id;
    };
    globalThis.addEventListener(PRIMARY_BIND_EVENT, onBind);
    return () => globalThis.removeEventListener(PRIMARY_BIND_EVENT, onBind);
  });
  const shownId = $derived(active === PRIMARY_SLOT ? boundSession : sessionIdOf(active, sessions.data));
  const shownRow = $derived(rowFor(sessions.data, shownId));
  const controller = $derived(active === PRIMARY_SLOT ? pageController() : overlayClient.slot === active ? overlayClient.client : null);
</script>

<div
  class="tw:flex tw:min-h-11 tw:min-w-0 tw:items-stretch tw:border-b tw:border-[var(--oc-line-chrome)] tw:bg-[var(--oc-ground-chrome)]"
  data-phone-tabs
  {@attach () => raiseFlag('phone-tabs')}
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
    <div class="tw:flex tw:min-h-11 tw:min-w-11 tw:items-stretch" data-phone-tabs-kebab>
      <TerminalUtilities slot={active} sessionId={shownId} {controller} width={0} appRows showsConnection={false} agentFamily={shownRow?.agent_family ?? null} />
    </div>
  </div>
</div>
{#if ctl.newAnchor}
  <CascadeMenu root={ctl.menu} anchor={ctl.newAnchor} label={t('opscenter.tabs.new')} onClose={() => (ctl.newAnchor = null)} />
{/if}
{#if ctl.tabMenuAnchor}
  <CascadeMenu root={ctl.tabMenuNodes} anchor={ctl.tabMenuAnchor} label={t('opscenter.tabs.menu_label')} onClose={ctl.closeTabMenu} />
{/if}
<LiveRegion store={terminalLayout} />
