<script lang="ts">
  /* the glance area the widgets page */
  import type { LayoutStore } from '../engine/layout.svelte';
  import type { CellId, InstanceKind, LayoutPage, SlotId } from '../engine/types';
  import { isWidgetDisabled } from '../../lib/item-settings/store.svelte';
  import { addBlocked, refusalLine, sessionInstanceId } from '../engine/components-actions';
  import { registeredInstanceKinds } from '../cells/registry';
  import { sessions } from '../api/sessions.svelte';
  import { browsers } from '../../lib/browser/api.svelte';
  import type { SessionInfo } from '../api/types';
  import { t } from '../../lib/i18n/index.svelte';
  import { categoryKey, offered, passesFilter } from './drawer-model';
  import { drawerList, isPanelRow, listKinds, type GroupRow } from './drawer-groups';
  import { buildView } from './drawer-view';
  import { widgetDrawerView } from './drawer-view-pref.svelte';
  import type { WindowChoice, WindowKind } from './WindowRows.svelte';
  import type { WidgetType } from '../widgets/types';
  import { isPopoutWindow } from '../widgets/fits';
  import { refusePlacement } from '../widgets/chrome/refusal-toast.svelte';
  import { panels } from '../engine/plugin-kinds';
  import { beginDrawerCarry, sidebarOffers, type CarryTarget } from './drawer-carry';
  import { repeatableInGlance } from '../../lib/drawer-zone/glance';
  import {
    addPanelWidget,
    addSessionWidget,
    addWidget,
    finishLayoutEditor,
    layoutEditor,
  } from './editor.svelte';
  import { analytics } from '../cells/analytics/state.svelte';
  import { FAMILY_TARGET_OPTION } from '../../lib/drawer-zone/glance-model';
  import { PRESETS, presetTitleKey } from '../viz/presets';
  import { manifestById } from '../widgets/core-manifests';
  import { drawerZone } from '../../lib/drawer-zone/zone-store.svelte';
  import { railStores } from '../../lib/session-rail/rail-store.svelte';
  import DuplicatePrompt from './DuplicatePrompt.svelte';
  import { askDuplicate, closeDuplicate } from './duplicate-prompt.svelte';
  import DrawerHead from './DrawerHead.svelte';
  import DrawerTools from './DrawerTools.svelte';
  import DrawerList from './DrawerList.svelte';
  import { addToRail, landRow } from './drawer-landing';

  let { store, page, docked = false }: { store: LayoutStore; page: LayoutPage; docked?: boolean } = $props();

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
    const refusal = await addSessionWidget(engineKind(kind), id, target?.area === 'surface' ? target.target : null);
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
  const chartRows = $derived(Object.values(analytics.charts));

  const inputs = $derived({
    page,
    onSurface,
    disabled: isWidgetDisabled,
    query,
    category: null,
    t: (key: string) => t(key),
  });
  const all = $derived(offered(inputs));
  const addableCount = $derived(all.filter((item) => item.state === 'addable').length);
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
    disabled: isWidgetDisabled,
    query: '',
    kind,
    extraWords: { 'core.analytics': [...analyticsWords, ...chartRows.map((chart) => chart.title)] },
    t: (key: string, params?: Record<string, string | number>) => t(key, params),
  });
  const grouped = $derived(drawerList(listInputs));
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
    if (isPanelRow(row)) {
      if (addPanelWidget(row.manifest.id, null, row.title)) store.announce(t('layout_editor.announce.added', { title: row.title }));
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
    void addWidget(row.cell);
  }

  function panelRowRect(widgetId: string): DOMRect | null {
    const rows = panel ? [...panel.querySelectorAll<HTMLElement>('[data-widget]')] : [];
    return rows.find((el) => el.dataset['widget'] === widgetId)?.getBoundingClientRect() ?? null;
  }

  function offerFor(row: GroupRow) {
    const refusal = row.state === 'refused' ? row.sentence : '';
    const surface = isPanelRow(row)
      ? row.state === 'placed'
        ? null
        : { cell: `${row.manifest.id}:${panels().tail(row.manifest.id) ?? 'panel'}` as SlotId, refusal }
      : row.family
        ? { cell: `${row.manifest.id.slice('core.'.length)}:new` as SlotId, refusal }
        : row.cell
          ? { cell: row.cell, refusal }
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




  function onPickerKey(event: KeyboardEvent): void {
    if (event.key !== 'Escape') return;
    event.preventDefault();
    event.stopPropagation();
    closePicker();
  }

</script>

<!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
<aside
  bind:this={panel}
  class="le-drawer"
  class:le-drawer--folded={folded}
  class:le-drawer--docked={docked}
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
      <button type="button" class="modal-btn modal-btn-confirm" data-layout-editor-done onclick={finishLayoutEditor}
        >{t('layout_editor.done')}</button
      >
    </div>
  </footer>
  <DuplicatePrompt />
</aside>

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
  .le-drawer {
    position: fixed;
    z-index: 40;
    top: 56px;
    right: 12px;
    bottom: 12px;
    display: flex;
    flex-direction: column;
    width: 300px;
    min-height: 0;
    background: var(--oc-ground-panel);
    border: var(--oc-border, 1px) solid var(--oc-line-panel);
    border-radius: var(--oc-radius, 2px);
    color: var(--oc-text-primary);
    font-family: var(--font-mono);
  }

  .le-drawer--folded {
    bottom: auto;
  }

  .le-drawer--docked {
    position: static;
    z-index: auto;
    flex: 1 1 auto;
    width: auto;
    border: 0;
    border-radius: 0;
  }

  .le-drawer :global(.le-chip) {
    padding: 2px var(--oc-space-2);
    border: var(--oc-border, 1px) solid var(--oc-line-faint);
    border-radius: var(--oc-radius-sm, 2px);
    background: transparent;
    color: var(--oc-text-muted);
    font-family: inherit;
    font-size: var(--oc-fs-micro);
    cursor: pointer;
  }

  .le-drawer :global(.le-chip--on) {
    border-color: var(--oc-orange-dim);
    background: var(--oc-orange-tint);
    color: var(--oc-orange);
  }

  .le-drawer :global(.le-hint),
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
    padding: 6px;
    overflow-y: auto;
    list-style: none;
  }

  .le-drawer :global(.le-card) {
    display: flex;
    align-items: center;
    gap: 10px;
    width: 100%;
    padding: 6px;
    border: var(--oc-border, 1px) solid transparent;
    border-radius: var(--oc-radius-sm, 2px);
    background: transparent;
    color: inherit;
    font-family: inherit;
    text-align: left;
    cursor: grab;
    touch-action: none;
  }

  .le-drawer :global(.le-card:hover:not(.le-card--placed)) {
    background: var(--oc-ground-hover);
    border-color: var(--oc-line-rule);
  }

  .le-drawer :global(.le-card--placed) {
    cursor: default;
    opacity: 0.6;
  }

  .le-drawer :global(.le-card:focus-visible),
  .le-drawer :global(.le-chip:focus-visible),
  .le-drawer :global(.le-input:focus-visible),
  .le-drawer :global(.le-fold:focus-visible) {
    outline: 2px solid var(--oc-cyan);
    outline-offset: 1px;
  }

  .le-drawer :global(.le-card__text) {
    display: flex;
    flex-direction: column;
    gap: 2px;
    min-width: 0;
  }

  .le-drawer :global(.le-card__name) {
    font-size: var(--oc-fs-body);
    color: var(--oc-text-primary);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .le-drawer :global(.le-card__meta) {
    font-size: var(--oc-fs-micro, var(--oc-fs-micro));
    letter-spacing: var(--oc-tracking-label, 0.6px);
    text-transform: uppercase;
    color: var(--oc-text-muted);
  }

  .le-foot {
    display: flex;
    flex-direction: column;
    gap: var(--oc-space-2);
    padding: 10px var(--oc-space-3);
    box-shadow: inset 0 1px 0 0 var(--oc-line-rule);
  }

  .le-foot__row {
    display: flex;
    justify-content: space-between;
    gap: var(--oc-space-2);
  }

  .le-foot :global(.modal-btn) {
    flex: 1 1 0;
    min-height: 30px;
    padding: 0 var(--oc-space-3);
    font-size: var(--oc-fs-body);
  }

  .le-ghost {
    position: fixed;
    z-index: 60;
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

  .le-drawer :global(.le-titlebar) {
    display: flex;
    align-items: center;
    gap: 10px;
    min-height: var(--oc-titlerow-h, 37px);
    padding: 0 var(--oc-space-2) 0 var(--oc-space-3);
    background: var(--oc-ground-titlerow);
    box-shadow: inset 0 -1px 0 0 var(--oc-line-rule);
  }

  .le-drawer :global(.le-tools) {
    display: flex;
    flex-direction: column;
    gap: var(--oc-space-2);
    padding: 10px var(--oc-space-3);
    box-shadow: inset 0 -1px 0 0 var(--oc-line-faint);
  }

  .le-drawer :global(.le-input) {
    padding: 7px 10px;
    border: var(--oc-border, 1px) solid var(--oc-line-rule);
    border-radius: var(--oc-radius-sm, 2px);
    background: var(--oc-ground-raised);
    color: var(--oc-text-primary);
    font-family: inherit;
    font-size: var(--oc-fs-status);
  }
</style>
