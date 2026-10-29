<script lang="ts">
  import type { MenuNode } from '../drawer-tabs/add-component-menu';
  import { t } from '../i18n/index.svelte';
  import { toggleLayoutEditor } from '../../opscenter/layout-editor/editor.svelte';
  import { canOpen } from '../../opscenter/layout-editor/empty-space-menu.svelte';
  import { allManifests, manifestById } from '../../opscenter/widgets/core-manifests';
  import { mergedIds, mergePlacement, viewOfPlacement } from '../../opscenter/widgets/views';
  import { CORE_ID } from '../widget-menu/model';
  import PlacementMenuHost from '../zone-shell/PlacementMenuHost.svelte';
  import { sidebarTabs } from '../dynamic-tabs/tab-store.svelte';
  import { widgetArea } from '../dynamic-tabs/widget-area.svelte';
  import { glanceFor, type PlacementOptions } from './glance';
  import { drawerZone } from './zone-store.svelte';

  let {
    placement,
    widget,
    options,
    anchor,
    onClose,
    onSettings,
  }: { placement: string; widget: string; options: PlacementOptions; anchor: HTMLElement | null; onClose: () => void; onSettings: (placement: string) => void } = $props();

  const stored = $derived(mergePlacement({ widget }, mergedIds(allManifests())));
  const manifest = $derived(manifestById(stored.widget));
  const declared = $derived(glanceFor(widget)?.options?.() ?? null);
  const title = $derived(manifest ? t(manifest.titleKey) : '');

  const copy = $derived(
    declared ? { schema: declared.schema, values: options, write: (key: string, value: boolean) => drawerZone.setGlanceOption(placement, key, value) } : undefined,
  );

  const settings = $derived.by((): MenuNode[] => {
    if (!declared || Object.values(declared.schema.fields).every((field) => field.kind === 'boolean')) return [];
    const key = placement;
    return [{ id: CORE_ID.settings, label: t('widgets.menu.settings'), icon: 'settings', run: () => onSettings(key) }];
  });

  function pickView(view: string): void {
    const next = manifest ? viewOfPlacement(manifest, view)?.widget : undefined;
    if (next) drawerZone.setGlanceWidget(placement, next);
  }

  const openArea = (): void => widgetArea.set(sidebarTabs.active(), 'full');
</script>

{#if manifest}
  <PlacementMenuHost
    host="glance"
    bodyHost="drawer"
    {manifest}
    view={stored.view ?? null}
    {options}
    placementKey={placement}
    {pickView}
    {copy}
    copyTail={settings}
    extras={{
      settings: [],
      editLayout: canOpen() ? () => void toggleLayoutEditor() : null,
      close: { run: () => void drawerZone.removeGlance(placement) },
    }}
    openHost={openArea}
    {anchor}
    label={t('drawer_zone.glance_area.options', { title })}
    {onClose}
  />
{/if}
