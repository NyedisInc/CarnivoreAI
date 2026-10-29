<script lang="ts">
  /* could not */
  import { META, isInstanceId, metaFor } from './meta';
  import { GUTTER } from './tracks';
  import { spanOf } from './spans';
  import { sizeOf, surfaceKeyOf } from './observe.svelte';
  import { viewport } from './viewport.svelte';
  import type { SlotId } from './types';
  import type { LayoutStore } from './layout.svelte';
  import { closeWidget } from './close-widget';
  import { editablePage, layoutEditor, removable, removeWidget, toggleLayoutEditor } from '../layout-editor/editor.svelte';
  import { t } from '../../lib/i18n/index.svelte';
  import { isConfigurable, openConfigure } from '../widgets/chrome/configure.svelte';
  import { fitsForSlot } from '../widgets/fits';
  import { manifestForSlot } from '../widgets/core-manifests';
  import { isPluginSlot, panels } from './plugin-kinds';
  import { drawerZone } from '../../lib/drawer-zone/zone-store.svelte';
  import { isWidgetId, openWidgetPopout } from '../../popout/popout';
  import { CORE_ID, type ArrangeEntry } from '../../lib/widget-menu/model';
  import PlacementMenuHost from '../../lib/zone-shell/PlacementMenuHost.svelte';
  import DeclaredTabMenu from '../../lib/zone-shell/DeclaredTabMenu.svelte';
  import { gridHeaderId } from '../shell/grid-zone';

  let {
    id,
    anchor,
    onClose,
    store,
  }: {
    id: SlotId;
    anchor: HTMLElement | null;
    onClose: () => void;
    store: LayoutStore;
  } = $props();

  const meta = $derived(metaFor(id, META));

  const title = $derived(meta.titleName ?? t(meta.titleKey));

  const instance = $derived(isInstanceId(id));

  const canLeave = $derived(removable(id));

  const headerShown = $derived(meta.chrome === 'card' && !meta.ownHead && viewport.wide ? store.isHeaderShown(id) : null);

  function onToggleHeader(): void {
    const shown = !store.isHeaderShown(id);
    store.setHeaderShown(id, shown);
    store.announce(t(shown ? 'widgets.menu.header_shown' : 'widgets.menu.header_hidden', { title }));
    close();
  }

  const span = $derived.by(() => {
    const row = store.state.layout.rows.find((one) => one.slots.some((slot) => slot.id === id));
    const slot = row?.slots.find((one) => one.id === id);
    return slot ? spanOf(slot) : 1;
  });
  const surfaceWidth = $derived(sizeOf(surfaceKeyOf(store.page)).width);
  const refusal = $derived(viewport.wide ? store.spanRefusal(id, surfaceWidth, GUTTER) : 'not-placed');
  const canSpanDown = $derived(refusal === null);

  const REFUSAL_KEYS: Readonly<Record<string, string>> = {
    'last-row': 'opscenter.menu.span_refused_last',
    'no-room': 'opscenter.menu.span_refused_room',
    max: 'opscenter.menu.span_refused_max',
    'not-placed': 'opscenter.menu.span_refused_last',
  };
  const refusalLine = $derived(refusal ? t(REFUSAL_KEYS[refusal] ?? 'opscenter.menu.span_refused_last') : '');

  const editing = $derived(layoutEditor.active && layoutEditor.page === store.page);
  const manifest = $derived(manifestForSlot(id));
  const configurable = $derived(isConfigurable(id));

  const canMoveToDrawer = $derived(
    !!manifest && !instance && store.page === 'home' && !drawerZone.items.some((item) => item.widget === manifest.id),
  );

  const pluginPopOutFits = $derived(isPluginSlot(id) && isWidgetId(id) && !panels().isPanel(id.split(':')[0] ?? '') ? fitsForSlot(id) : null);

  const canPopOut = $derived((!!manifest && !instance && isWidgetId(manifest.id)) || pluginPopOutFits !== null);

  function onPopOut(): void {
    const target = manifest;
    const pluginFits = pluginPopOutFits;
    if (pluginFits) openWidgetPopout(id, pluginFits);
    else if (target) openWidgetPopout(target.id, target.fits);
  }

  function close(): void {
    onClose();
    anchor?.focus();
  }

  function onSpanDown(): void {
    if (!store.spanDown(id, surfaceWidth, GUTTER)) return;
    store.announce(t('opscenter.menu.spanned', { title, rows: span + 1 }));
    close();
  }

  function onSpanUp(): void {
    store.spanUp(id);
    store.announce(t('opscenter.menu.spanned', { title, rows: Math.max(1, span - 1) }));
    close();
  }

  function onConfigure(): void {
    openConfigure(id);
  }

  function onMoveToDrawer(): void {
    const widget = manifest?.id;
    const line = t('widgets.menu.moved_to_drawer', { title });
    if (!widget) return;
    if (drawerZone.add(widget)) {
      void removeWidget(id);
      store.announce(line);
    }
  }

  /*  hidden  */
  function onCloseWidget(): void {
    const from = anchor ? anchor.getBoundingClientRect() : null;
    closeWidget(store, id, { editing, from });
  }

  const arrange = $derived.by((): ArrangeEntry[] => {
    const out: ArrangeEntry[] = [];
    if (viewport.wide) {
      out.push({ item: 'extendRow', blocked: canSpanDown ? undefined : refusalLine, run: onSpanDown });
      out.push({ item: 'pullBackRow', blocked: span < 2 ? t('widgets.menu.one_row') : undefined, run: onSpanUp });
    }
    if (canMoveToDrawer) out.push({ item: 'moveToDrawer', run: onMoveToDrawer });
    return out;
  });

  const canEdit = $derived(viewport.wide && (editing || editablePage() === store.page));

  const extras = $derived({
    settings: configurable ? [[{ id: CORE_ID.settings, label: t('widgets.menu.settings'), icon: 'settings', run: onConfigure }]] : [],
    popOut: canPopOut ? onPopOut : null,
    header: headerShown === null ? null : { shown: headerShown, toggle: onToggleHeader },
    arrange,
    editLayout: canEdit ? () => void toggleLayoutEditor() : null,
    close: canLeave ? { instance, run: onCloseWidget } : null,
  });
  const label = $derived(t('opscenter.frame.options', { title }));
</script>

{#if manifest}
  <PlacementMenuHost host="grid" bodyHost={{ drawn: gridHeaderId(id) }} {editing} {manifest} placementKey={id} {extras} {anchor} {label} {onClose} />
{:else}
  <DeclaredTabMenu hostId={gridHeaderId(id)} {editing} {extras} {anchor} {label} {onClose} />
{/if}
