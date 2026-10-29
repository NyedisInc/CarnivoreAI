<script lang="ts">
  /* pop-out window */
  import { onMount, untrack } from 'svelte';
  import { entryFor } from '../opscenter/cells/registry';
  import { META } from '../opscenter/engine/meta';
  import type { CellId } from '../opscenter/engine/types';
  import { manifestById } from '../opscenter/widgets/core-manifests';
  import { sessionScopeFor } from '../opscenter/widgets/session-scope';
  import PlacementBody from '../lib/zone-shell/PlacementBody.svelte';
  import ZoneShell from '../lib/zone-shell/ZoneShell.svelte';
  import { createZone } from '../lib/zone-shell/zone.svelte';
  import { HOST_LOOKS } from '../lib/zone-shell/host-looks';
  import type { TabRef } from '../lib/zone-shell/zone-types';
  import PluginTab from './PluginTab.svelte';
  import { widgetPath, type PopoutPlacement } from './popout';
  import { resolvePlacement } from '../opscenter/widgets/placement-resolve';
  import { auth, initAuth, sessions, startEvents } from '../opscenter/api';
  import { watchViewport } from '../opscenter/engine/viewport.svelte';
  import { t } from '../lib/i18n/index.svelte';
  import WidgetHead from '../opscenter/shell/WidgetHead.svelte';
  import CornerMenu from '../opscenter/shell/CornerMenu.svelte';
  import PopoutMenu from './PopoutMenu.svelte';
  import type { MenuSlot } from '../opscenter/shell/widget-head';
  import type { FrameHeader } from '../opscenter/shell/frame-header.svelte';
  import { followEnablement } from '../cplugs/host/enablement.svelte';
  import { enablementKnown, popoutWidgetFor } from '../cplugs/host/popout-widgets';

  let { widget, placement = {} }: { widget: string; placement?: PopoutPlacement } = $props();

  const plugin = $derived(widget.startsWith('core.') ? null : popoutWidgetFor(widget));
  const manifest = $derived(manifestById(widget));
  let view = $state<string | null>(untrack(() => placement.view ?? null));
  const cell = $derived((resolvePlacement({ widget, view })?.slot ?? widget.slice('core.'.length)) as CellId);
  const Cell = $derived(plugin ? (plugin.enabled ? plugin.widget.component : undefined) : entryFor(cell)?.component);
  const meta = $derived(plugin ? plugin.widget.meta : META[cell]);
  const titleKey = $derived(plugin ? plugin.widget.meta.titleKey : manifest?.titleKey);
  const waiting = $derived(!!plugin && !enablementKnown());
  const key = $derived(`popout-widget:${widget}`);
  const scope = $derived(placement.sessionId ? sessionScopeFor(sessions.data, placement.sessionId) : undefined);

  function pickView(next: string): void {
    view = next;
    history.replaceState(null, '', widgetPath(widget, { sessionId: placement.sessionId, view: next, options: placement.options }));
  }

  const zone = createZone({
    key: 'popout',
    tabs: (): readonly TabRef[] => [{ key: widget, kind: 'widget' }],
    active: () => widget,
    select: () => {},
    panel: () => 'open',
    strip: 'none',
    toolbar: 'header',
    menuHost: 'popout',
    headerId: () => HOST_LOOKS.popout.keyFor({ id: !plugin && manifest ? (resolvePlacement({ widget, view })?.cell.id ?? widget) : widget }, null, null),
  });

  $effect(() => watchViewport());
  onMount(() => {
    initAuth();
    startEvents();
    if (!widget.startsWith('core.')) followEnablement();
  });
</script>

{#snippet popHead(header: FrameHeader)}
  {#snippet menu(slot: MenuSlot)}
    <PopoutMenu hostId={key} title={header.title || t(titleKey!)} anchor={slot.anchor} onClose={slot.close} manifest={manifest} {view} {pickView} />
  {/snippet}
  {#snippet corner()}
    <CornerMenu {meta} title={t(titleKey!)} editing={false} place="row" {menu} />
  {/snippet}
  <WidgetHead {meta} {header} title={header.title || t(titleKey!)} {corner} onClose={() => window.close()} withRight={false} />
{/snippet}

{#snippet tabBody()}
  {#if plugin}
    <PluginTab {widget} {key} Cell={Cell!} meta={meta!} label={t(titleKey!)} head={popHead} />
  {:else if manifest}
    <PlacementBody host="popout" {manifest} {view} options={placement.options} {scope} head={popHead} />
  {/if}
{/snippet}

{#if auth.state === 'signed-out'}
  <p class="sw-notice" role="status">{t('opscenter.popout.signed_out')}</p>
{:else if waiting}
  <p class="sw-notice" role="status" data-widget-loading></p>
{:else if !(plugin || manifest) || !Cell || !meta}
  <p class="sw-notice" role="status" data-widget-unavailable>{t('opscenter.popout.widget_unavailable', { id: widget })}</p>
{:else}
  <ZoneShell {zone} tab={tabBody} />
{/if}

<style>
  @layer components {
    .sw-notice {
      margin: var(--oc-space-4);
      color: var(--oc-text-muted);
      font: var(--oc-fs-label) var(--font-mono);
      letter-spacing: 0.08em;
    }
  }
</style>
