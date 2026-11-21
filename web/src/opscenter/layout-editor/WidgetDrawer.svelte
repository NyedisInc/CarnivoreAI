<script lang="ts">
  /* the widgets page */
  import type { LayoutStore } from '../engine/layout.svelte';
  import { takenSlots } from '../engine/components-actions';
  import { isTabSlot } from '../engine/tabs';
  import { tabsFor } from '../engine/tab-groups.svelte';
  import type { CellId, InstanceKind, LayoutPage, SlotId } from '../engine/types';
  import { isWidgetDisabled } from '../../lib/item-settings/store.svelte';
  import { addBlocked, refusalLine, sessionInstanceId } from '../engine/components-actions';
  import { registeredInstanceKinds } from '../cells/registry';
  import { sessions } from '../api/sessions.svelte';
  import { browsers } from '../../lib/browser/api.svelte';
  import type { SessionInfo } from '../api/types';
  import { t } from '../../lib/i18n/index.svelte';
  import { categoryKey, passesFilter } from './drawer-model';
  import { drawerList, listKinds, type GroupRow } from './drawer-groups';
  import { buildView } from './drawer-view';
  import { widgetDrawerView } from './drawer-view-pref.svelte';
  import type { WindowChoice, WindowKind } from './WindowRows.svelte';
  import type { WidgetType } from '../widgets/types';
  import { isPopoutWindow } from '../widgets/fits';
  import { refusePlacement } from '../widgets/chrome/refusal-toast.svelte';
  import { beginDrawerCarry, sidebarOffers, type CarryTarget } from './drawer-carry';
  import { dropHostById } from '../../lib/motion-grid';
  import { repeatableInGlance } from '../../lib/drawer-zone/glance';
  import {
    addGalleryPreset,
    addSessionWidget,
    addWidget,
    closeWidgetDrawer,
    finishLayoutEditor,
    layoutEditor,
  } from './editor.svelte';
  import { analytics } from '../cells/analytics/state.svelte';
  import { FAMILY_TARGET_OPTION } from '../../lib/drawer-zone/glance-model';
  import { PRESETS, presetConfig, presetTitleKey, type Preset } from '../viz/presets';
  import { PRESET_KIND } from './drop-kind';
  import { manifestById } from '../widgets/core-manifests';
  import { drawerZone } from '../../lib/drawer-zone/zone-store.svelte';
  import { railStores } from '../../lib/session-rail/rail-store.svelte';
  import Button from '../../lib/base/Button.svelte';
  import Sheet from '../../lib/sheet/Sheet.svelte';
  import DuplicatePrompt from './DuplicatePrompt.svelte';
  import { askDuplicate, closeDuplicate } from './duplicate-prompt.svelte';
  import DrawerHead from './DrawerHead.svelte';
  import DrawerTools from './DrawerTools.svelte';
  import DrawerList from './DrawerList.svelte';
  import { addToRail, landFamilyCopy, landRow } from './drawer-landing';

  let { store, page, docked = false, surface = null }: { store: LayoutStore; page: LayoutPage; docked?: boolean; surface?: string | null } = $props();

  async function addRow(row: GroupRow, cell: SlotId): Promise<void> {
    if (surface && surface !== 'dashboard') {
      dropHostById(surface)?.add?.(surface.startsWith('zone:') ? row.widgetId : cell);
      return;
    }
    await addWidget(cell);
  }

  type PickerKind = WindowKind;

  function engineKind(kind: PickerKind): InstanceKind {
    return kind === 'browser' ? 'browser' : 'terminal';
  }

  function isShell(row: SessionInfo): boolean {
    return row.agent_family === 'shell';
  }

  let panel = $state<HTMLElement | null>(null);
  let query = $state('');
  let kind = $state<WidgetType | null>(null);
  let folded = $state(false);
  let carrying = $state<{ title: string; x: number; y: number; target: boolean } | null>(null);
  let lastPointer = { x: 0, y: 0 };
  $effect(() => () => closeDuplicate());
  let swallowClick = false;
  let swallowChoice = false;

  let picker = $state<PickerKind | null>(null);
  let pickerTarget = $state<CarryTarget | null>(null);
  let pickerRefusal = $state('');

  const instanceKinds = $derived(registeredInstanceKinds());
  /* the home screen */
  const showSessionEntries = $derived(instanceKinds.includes('terminal'));
  const showBrowserEntry = $derived(instanceKinds.includes('browser'));
  const windowKinds = $derived<WindowKind[]>([
    ...(showSessionEntries ? (['session', 'terminal'] as const) : []),
    ...(showBrowserEntry ? (['browser'] as const) : []),
  ]);

  const sessionRows = $derived(((sessions.data ?? []) as SessionInfo[]).filter((row) => !isShell(row)));
  const terminalRows = $derived(((sessions.data ?? []) as SessionInfo[]).filter(isShell));
  const browserRows = $derived(browsers.data ?? []);

  const pickerRows = $derived((kind: PickerKind): WindowChoice[] => {
    const rows =
      kind === 'session'
        ? sessionRows.map((row) => ({ id: row.session.id, label: row.label ?? row.session.id }))
        : kind === 'terminal'
          ? terminalRows.map((row) => ({ id: row.session.id, label: row.label ?? row.session.id }))
          : browserRows.map((b) => ({ id: b.id, label: b.label || b.id }));
    return rows.map((row) => ({ ...row, why: picker === kind && pickerToSidebar ? '' : addBlocked(store, engineKind(kind), row.id) }));
  });

  function openPicker(kind: PickerKind, target: CarryTarget | null): void {
    picker = kind;
    pickerTarget = target;
    pickerRefusal = '';
  }

  function closePicker(): void {
    picker = null;
    pickerTarget = null;
    pickerRefusal = '';
  }

  const pickerToSidebar = $derived(pickerTarget !== null && pickerTarget.area !== 'surface');

  async function onPick(kind: PickerKind, id: string, target: CarryTarget | null): Promise<void> {
    if (target && target.area !== 'surface') {
      const engine = engineKind(kind);
      const widget = `core.${engine}`;
      const aim = sessionInstanceId(engine, id).slice(engine.length + 1);
      const title = t(`layout_editor.drawer.${kind}`);
      const added = target.area === 'rail'
        ? addToRail(store, target.edge, widget, title, target.spot, aim)
        : target.area === 'zone'
        ? drawerZone.add(widget, target.index, aim)
        : drawerZone.addGlance(widget, true, target.index, { [FAMILY_TARGET_OPTION]: aim }) !== null;
      if (added && target.area !== 'rail') store.announce(t(target.area === 'zone' ? 'layout_editor.announce.zone_added' : 'layout_editor.announce.glance_added', { title }));
      pickerRefusal = added ? '' : t('opscenter.components.add_duplicate');
      if (!pickerRefusal) pickerTarget = null;
      return;
    }
    const refusal = await addSessionWidget(engineKind(kind), id, null);
    pickerRefusal = refusalLine(refusal, engineKind(kind));
    if (!pickerRefusal) pickerTarget = null;
  }

  function onPickerCardClick(kind: PickerKind): void {
    if (swallowClick) {
      swallowClick = false;
      return;
    }
    if (picker === kind) closePicker();
    else openPicker(kind, null);
  }

  function onChoiceClick(kind: PickerKind, choice: WindowChoice): void {
    if (swallowChoice) {
      swallowChoice = false;
      return;
    }
    if (choice.why) return;
    void onPick(kind, choice.id, pickerTarget);
  }

  function onChoiceDown(event: PointerEvent, kind: PickerKind, choice: WindowChoice): void {
    const card = event.currentTarget as HTMLElement;
    const none = { refusal: '', moves: null };
    const offer = { surface: { cell: `picker:${kind}` as SlotId, refusal: addBlocked(store, engineKind(kind), choice.id) }, zone: none, glance: none };
    beginDrawerCarry(card, event, offer, store, page, panel, {
      onMove: (x, y, aimed) => {
        carrying = { title: choice.label, x, y, target: aimed };
      },
      onDrop: (target) => {
        void onPick(kind, choice.id, target);
      },
      onRefuse: (sentence) => refusePlacement(sentence),
      onEnd: (lifted) => {
        carrying = null;
        swallowChoice = lifted;
        if (lifted) setTimeout(() => (swallowChoice = false), 0);
      },
    });
  }

  function onPickerCardDown(event: PointerEvent, kind: PickerKind): void {
    const card = event.currentTarget as HTMLElement;
    const none = { refusal: '', moves: null };
    const offer = { surface: { cell: `picker:${kind}` as SlotId, refusal: '' }, zone: none, glance: none };
    beginDrawerCarry(card, event, offer, store, page, panel, {
      onMove: (x, y, aimed) => {
        carrying = { title: t(`layout_editor.drawer.${kind}`), x, y, target: aimed };
      },
      onDrop: (target) => {
        openPicker(kind, target);
      },
      onRefuse: (sentence) => refusePlacement(sentence),
      onEnd: (lifted) => {
        carrying = null;
        swallowClick = lifted;
        if (lifted) setTimeout(() => (swallowClick = false), 0);
      },
    });
  }

  const onSurface = $derived<SlotId[]>(
    store.state.layout.rows.flatMap((row) => row.slots.map((slot) => slot.id)),
  );
  const layoutTabs = $derived<string[]>(
    page === 'terminal' ? takenSlots(store).filter(isTabSlot).flatMap((slot) => tabsFor(store, slot)) : [],
  );
  const chartRows = $derived(Object.values(analytics.charts));

  const inputs = $derived({
    page,
    onSurface,
    tabs: layoutTabs,
    disabled: isWidgetDisabled,
    query,
    category: null,
    t: (key: string) => t(key),
  });
  const PAGE_KEYS = { home: 'layout_editor.page.home', terminal: 'layout_editor.page.terminal', warroom: 'layout_editor.page.warroom' } as const;
  const pageName = $derived(t(PAGE_KEYS[page]));

  const analyticsCategory = manifestById('core.analytics')!.category;
  const analyticsWords = $derived([
    t('analytics.add_chart'),
    t('gallery.title'),
    t('analytics.monitoring'),
    'core.analytics',
    ...PRESETS.map((preset) => t(presetTitleKey(preset))),
  ]);
  let galleryOpen = $state(false);
  const needle = $derived(query.trim().toLowerCase());
  const showAnalytics = $derived(passesFilter(inputs, analyticsCategory, analyticsWords));

  const listInputs = $derived({
    onSurface,
    tabs: layoutTabs,
    disabled: isWidgetDisabled,
    query: '',
    kind,
    extraWords: { 'core.analytics': [...analyticsWords, ...chartRows.map((chart) => chart.title)] },
    t: (key: string, params?: Record<string, string | number>) => t(key, params),
  });
  const grouped = $derived(drawerList(listInputs));
  const addableCount = $derived(grouped.rows.filter((row) => row.state === 'addable').length);
  function searchWords(row: GroupRow): string[] {
    return [t(categoryKey(row.manifest.category)), t(`widgets.type.${row.type}`), row.widgetId, ...((listInputs.extraWords as Record<string, readonly string[]>)[row.widgetId] ?? [])];
  }
  const view = $derived(buildView(grouped.rows, widgetDrawerView.mode, query, searchWords, (type) => t(`widgets.type.${type}`)));
  const viewCount = $derived(view.flat.length + view.sections.reduce((sum, section) => sum + section.rows.length, 0));
  const kinds = $derived(listKinds(listInputs));
  const inPopout = isPopoutWindow();

  function familyOpen(row: GroupRow): boolean | null {
    return row.widgetId === 'core.analytics' ? galleryOpen || needle !== '' : null;
  }

  const emptyLine = $derived(
    viewCount > 0 ? '' : needle === '' && kind === null ? t('layout_editor.drawer.none') : t('layout_editor.drawer.no_match'),
  );

  function onRowClick(row: GroupRow): void {
    if (swallowClick) {
      swallowClick = false;
      return;
    }
    if (row.state === 'refused') {
      refusePlacement(row.sentence);
      return;
    }
    if (row.widgetId === 'core.analytics') {
      galleryOpen = !galleryOpen;
      return;
    }
    if (row.state === 'placed' && !row.family) {
      const rect = panelRowRect(row.widgetId);
      askDuplicate({ kind: 'here', title: row.title, x: rect?.left ?? 0, y: rect?.bottom ?? 0 });
      return;
    }
    if (row.state !== 'addable' || !row.cell) return;
    void addRow(row, row.cell);
  }

  function panelRowRect(widgetId: string): DOMRect | null {
    const rows = panel ? [...panel.querySelectorAll<HTMLElement>('[data-widget]')] : [];
    return rows.find((el) => el.dataset['widget'] === widgetId)?.getBoundingClientRect() ?? null;
  }

  function offerFor(row: GroupRow) {
    const refusal = row.state === 'refused' ? row.sentence : '';
    const surface = row.cell
      ? { cell: row.cell, refusal }
      : row.family
        ? { cell: `${row.manifest.id.slice('core.'.length)}:new` as SlotId, refusal }
        : null;
    const none = { refusal: '', moves: null };
    const holds = (zone: readonly string[]) => sidebarOffers(row.manifest, row.title, {
      zone,
      glance: drawerZone.glance,
      disabled: isWidgetDisabled,
      repeatable: repeatableInGlance,
      t: (key, params) => t(key, params),
    });
    const sidebar = inPopout ? { zone: none, glance: none } : holds(drawerZone.items.map((item) => item.widget));
    const rail = inPopout ? none : holds(Object.values(railStores).flatMap((store) => store.items.map((item) => item.widget))).zone;
    return { surface, ...sidebar, rail };
  }


  function onRowDown(event: PointerEvent, row: GroupRow): void {
    const card = event.currentTarget as HTMLElement;
    beginDrawerCarry(card, event, offerFor(row), store, page, panel, {
      onMove: (x, y, aimed) => {
        carrying = { title: row.title, x, y, target: aimed };
        lastPointer = { x, y };
      },
      onDrop: (target) => landRow(store, row, target, lastPointer),
      onRefuse: (sentence) => refusePlacement(sentence),
      onEnd: (lifted) => {
        carrying = null;
        swallowClick = lifted;
        if (lifted) setTimeout(() => (swallowClick = false), 0);
      },
    });
  }




  function onGalleryDown(event: PointerEvent, preset: Preset): void {
    const row = grouped.rows.find((one) => one.widgetId === 'core.analytics');
    if (!row) return;
    const offer = offerFor(row);
    const surface = offer.surface ? { ...offer.surface, cell: `${PRESET_KIND}${preset.id}` as SlotId } : null;
    beginDrawerCarry(event.currentTarget as HTMLElement, event, { ...offer, surface }, store, page, panel, {
      onMove: (x, y, aimed) => {
        carrying = { title: t(presetTitleKey(preset)), x, y, target: aimed };
      },
      onDrop: (target) => landFamilyCopy(store, row, target, presetConfig(preset)),
      onRefuse: (sentence) => refusePlacement(sentence),
      onEnd: (lifted) => {
        carrying = null;
        swallowClick = lifted;
        if (lifted) setTimeout(() => (swallowClick = false), 0);
      },
    });
  }

  function onGalleryPick(preset: Preset): void {
    if (swallowClick) {
      swallowClick = false;
      return;
    }
    if (surface && surface !== 'dashboard') dropHostById(surface)?.add?.(surface.startsWith('zone:') ? 'core.analytics' : `${PRESET_KIND}${preset.id}`);
    else addGalleryPreset(preset);
  }

  function onPickerKey(event: KeyboardEvent): void {
    if (event.key !== 'Escape') return;
    event.preventDefault();
    event.stopPropagation();
    closePicker();
  }

</script>

<Sheet
  place="float"
  phone={false}
  {folded}
  {docked}
  width="var(--oc-sheet-w-narrow)"
  bind:el={panel}
  class="le-drawer"
  aria-label={t('layout_editor.drawer.label')}
  data-layout-editor-drawer={page}
  onkeydown={(event) => picker && onPickerKey(event)}
>
  <DrawerHead {pageName} {docked} bind:folded />

  {#if !folded}
    
    <DrawerTools bind:query bind:kind {kinds} {addableCount} />

    <ul class="le-list" aria-label={t('layout_editor.drawer.list')}>
      <DrawerList
        {windowKinds}
        {picker}
        {pickerRows}
        {pickerTarget}
        {pickerRefusal}
        {onPickerCardDown}
        {onPickerCardClick}
        {onChoiceDown}
        {onChoiceClick}
        {view}
        {query}
        {needle}
        {galleryOpen}
        {familyOpen}
        {onRowDown}
        {onRowClick}
        onCardDown={onGalleryDown}
        onCardPick={onGalleryPick}
        {inputs}
        {onSurface}
        {showAnalytics}
        {pageName}
      />
    </ul>
    {#if emptyLine}
      <p class="le-empty" role="status">{emptyLine}</p>
    {/if}
  {/if}

  <footer class="le-foot">
    <div class="le-foot__row">
      <Button variant="confirm" data-layout-editor-done onclick={surface ? closeWidgetDrawer : finishLayoutEditor}>{t('layout_editor.done')}</Button>
    </div>
  </footer>
  <DuplicatePrompt />
</Sheet>

{#if carrying}
  <div
    class="le-ghost"
    class:le-ghost--aimed={carrying.target}
    style={`left: ${Math.round(carrying.x + 12)}px; top: ${Math.round(carrying.y + 12)}px`}
    aria-hidden="true"
  >
    {carrying.title}
  </div>
{/if}

<style>

  @layer components {
    :global(.le-drawer) {
      transition: transform var(--oc-motion) ease-out;
    }

    :global(body.grid-carrying) :global(.le-drawer:not([data-sheet-docked])) {
      transform: translateX(calc(100% + var(--oc-space-5)));
      pointer-events: none;
    }

    @media (prefers-reduced-motion: reduce) {
      :global(.le-drawer) {
        transition: none;
      }
    }
  }

  :global(.le-drawer) :global(.le-hint),
  .le-empty {
    margin: 0;
    font-size: var(--oc-fs-label, var(--oc-fs-label));
    color: var(--oc-text-muted);
  }

  .le-empty {
    padding: var(--oc-space-3);
  }

  .le-list {
    flex: 1 1 auto;
    min-height: 0;
    margin: 0;
    padding: var(--oc-space-1-5);
    overflow-y: auto;
    list-style: none;
  }

  :global(.le-drawer) :global([data-le-card]) {
    align-items: center;
    gap: var(--oc-gap-parts);
    width: 100%;
    padding: var(--oc-space-1-5);
    color: inherit;
    cursor: grab;
    touch-action: none;
  }

  :global(.le-drawer) :global([data-le-card][data-placed]) {
    cursor: default;
    opacity: 0.6;
  }

  :global(.le-drawer) :global(.le-card__text) {
    display: flex;
    flex-direction: column;
    gap: var(--oc-space-0-5);
    min-width: 0;
  }

  :global(.le-drawer) :global(.le-card__name) {
    font-size: var(--oc-fs-body);
    color: var(--oc-text-primary);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  :global(.le-drawer) :global(.le-card__meta) {
    font-size: var(--oc-fs-micro, var(--oc-fs-micro));
    letter-spacing: var(--oc-tracking-label, 0.6px);
    text-transform: uppercase;
    color: var(--oc-text-muted);
  }

  .le-foot {
    display: flex;
    flex-direction: column;
    gap: var(--oc-space-2);
    padding: calc(var(--oc-space-2) + var(--oc-space-0-5)) var(--oc-space-3);
    box-shadow: inset 0 1px 0 0 var(--oc-line-rule);
  }

  .le-foot__row {
    display: flex;
    justify-content: space-between;
    gap: var(--oc-space-2);
  }

  .le-foot :global([data-btn]) {
    flex: 1 1 0;
    min-height: 30px;
    padding: 0 var(--oc-space-3);
    font-size: var(--oc-fs-body);
  }

  .le-ghost {
    position: fixed;
    z-index: var(--oc-z-sheet);
    padding: var(--oc-space-1) var(--oc-space-2);
    pointer-events: none;
    background: var(--oc-ground-raised);
    border: var(--oc-border, 1px) dashed var(--oc-line-rule);
    border-radius: var(--oc-radius-sm, 2px);
    color: var(--oc-text-secondary);
    font-family: var(--font-mono);
    font-size: var(--oc-fs-label);
  }

  .le-ghost--aimed {
    border-color: var(--oc-cyan);
    color: var(--oc-text-primary);
  }

  :global(.le-drawer) :global(.le-titlebar) {
    display: flex;
    align-items: center;
    gap: var(--oc-gap-parts);
    min-height: var(--oc-titlerow-h, 37px);
    padding: 0 var(--oc-space-2) 0 var(--oc-space-3);
    background: var(--oc-ground-titlerow);
    box-shadow: inset 0 -1px 0 0 var(--oc-line-rule);
  }

  :global(.le-drawer) :global(.le-tools) {
    display: flex;
    flex-direction: column;
    gap: var(--oc-space-2);
    padding: calc(var(--oc-space-2) + var(--oc-space-0-5)) var(--oc-space-3);
    box-shadow: inset 0 -1px 0 0 var(--oc-line-faint);
  }
</style>
