
import { tick } from 'svelte';
import { flipCells, measureCells } from '../engine/flip';
import type { DropTarget, LayoutStore } from '../engine/layout.svelte';
import { META, isInstanceId, metaFor } from '../engine/meta';
import { PRIMARY_SLOT, type AddRefusal } from '../engine/model';
import { addSession, sessionInstanceId } from '../engine/components-actions';
import { flushSave } from '../engine/persist';
import { viewport } from '../engine/viewport.svelte';
import type { InstanceKind, LayoutPage, SlotId } from '../engine/types';
import { storeFor, surfacePage } from '../../lib/drawer-tabs/drawer-surface.svelte';
import { t } from '../../lib/i18n/index.svelte';
import { panels } from '../engine/plugin-kinds';
import { GUTTER } from '../engine/tracks';
import { refusePlacement } from '../widgets/chrome/refusal-toast.svelte';
import { addChart, flushChartView, saveChartSettings } from '../cells/analytics/state.svelte';
import type { ChartConfig } from '../cells/analytics/types';
import { presetConfig, type Preset } from '../viz/presets';
import { galleryTarget } from './gallery-place';

export const EDITING_CLASS = 'oc-layout-editing';

export const layoutEditor: {
  active: boolean;
  page: LayoutPage | null;
  revision: number;
  focusSlot: SlotId | null;
} = $state({ active: false, page: null, revision: 0, focusSlot: null });

let editing: { store: LayoutStore; session: string } | null = null;

export const editorSeams: {
  page: () => LayoutPage | null;
  store: (page: LayoutPage) => LayoutStore | null;
  wide: () => boolean;
} = {
  page: () => (typeof document === 'undefined' ? null : surfacePage(document)),
  store: (page) => storeFor(page),
  wide: () => viewport.wide,
};

export function slotTitle(id: SlotId): string {
  const meta = metaFor(id, META);
  return meta.titleName ?? t(meta.titleKey);
}

function repaintBar(): void {
  const bar = (globalThis as { SessionSidebarBar?: { paint?: () => void } }).SessionSidebarBar;
  try {
    bar?.paint?.();
  } catch (error) {
    console.warn('[layout-editor] bar repaint failed', error);
  }
}

function markBody(on: boolean): void {
  if (typeof document === 'undefined') return;
  document.body.classList.toggle(EDITING_CLASS, on);
  if (on && layoutEditor.page) document.body.dataset['layoutEditing'] = layoutEditor.page;
  else delete document.body.dataset['layoutEditing'];
}

export function editingStore(): LayoutStore | null {
  return editing?.store ?? null;
}

export function editablePage(): LayoutPage | null {
  if (!editorSeams.wide()) return null;
  const page = editorSeams.page();
  return page && editorSeams.store(page) ? page : null;
}

export function enterLayoutEditor(): boolean {
  if (layoutEditor.active) return true;
  const page = editablePage();
  const store = page ? editorSeams.store(page) : null;
  if (!page || !store) return false;
  editing = { store, session: store.session };
  layoutEditor.active = true;
  layoutEditor.page = page;
  layoutEditor.focusSlot = null;
  layoutEditor.revision += 1;
  markBody(true);
  store.announce(t('layout_editor.announce.on'));
  repaintBar();
  return true;
}

function end(line: string): void {
  const store = editing?.store;
  editing = null;
  layoutEditor.active = false;
  layoutEditor.page = null;
  layoutEditor.focusSlot = null;
  layoutEditor.revision += 1;
  markBody(false);
  if (store && line) store.announce(line);
  repaintBar();
}

export function finishLayoutEditor(): void {
  if (!layoutEditor.active) return;
  end(t('layout_editor.announce.saved'));
}

export function toggleLayoutEditor(): boolean {
  if (layoutEditor.active) {
    finishLayoutEditor();
    return false;
  }
  return enterLayoutEditor();
}

export function checkLayoutEditor(): void {
  if (!editing) return;
  const gone =
    !editorSeams.wide() || editorSeams.page() !== layoutEditor.page || editing.store.session !== editing.session;
  if (gone) end('');
}

function live(): LayoutStore | null {
  checkLayoutEditor();
  return editing?.store ?? null;
}

async function animated(store: LayoutStore, act: () => boolean, line: string): Promise<boolean> {
  const before = measureCells();
  const changed = act();
  layoutEditor.revision += 1;
  if (!changed) return false;
  await tick();
  flipCells(before);
  store.announce(line);
  return true;
}

export async function addWidget(id: SlotId): Promise<boolean> {
  const store = live();
  if (!store) return false;
  if (store.state.layout.rows.some((row) => row.slots.some((slot) => slot.id === id))) return false;
  const before = store.state.layout;
  const done = await animated(
    store,
    () => {
      store.show(id);
      return store.state.layout !== before;
    },
    t('layout_editor.announce.added', { title: slotTitle(id) }),
  );
  return done;
}

export async function dropWidget(id: SlotId, target: DropTarget): Promise<'landed' | 'placed' | 'unchanged'> {
  const store = live();
  if (!store) return 'unchanged';
  let outcome: 'landed' | 'placed' | 'unchanged' = 'unchanged';
  const line = (): string =>
    t(outcome === 'landed' ? 'layout_editor.announce.dropped' : 'layout_editor.announce.added', {
      title: slotTitle(id),
    });
  const before = measureCells();
  outcome = store.showAt(id, target);
  layoutEditor.revision += 1;
  if (outcome === 'unchanged') {
    return outcome;
  }
  await tick();
  flipCells(before);
  store.announce(line());
  return outcome;
}

export async function addSessionWidget(
  kind: InstanceKind,
  sessionId: string,
  target: DropTarget | null,
): Promise<AddRefusal> {
  const store = live();
  if (!store) return 'no-row';
  let refusal: AddRefusal = null;
  const done = await animated(
    store,
    () => {
      const before = store.state.layout;
      refusal = addSession(store, kind, sessionId);
      if (refusal) return false;
      if (target) store.moveTo(sessionInstanceId(kind, sessionId), target);
      return store.state.layout !== before;
    },
    t('layout_editor.announce.added', { title: sessionId }),
  );
  return refusal;
}

export function removable(id: SlotId): boolean {
  return id !== PRIMARY_SLOT;
}

export async function removeWidget(id: SlotId): Promise<boolean> {
  const store = live();
  if (!store || !removable(id)) return false;
  const title = slotTitle(id);
  const before = store.state.layout;
  const done = await animated(
    store,
    () => {
      if (isInstanceId(id)) store.remove(id);
      else store.hide(id);
      return store.state.layout !== before;
    },
    t('layout_editor.announce.removed', { title }),
  );
  return done;
}

export function addAnalyticsWidget(copy?: ChartConfig, target?: DropTarget | null): boolean {
  const store = live();
  if (!store) return false;
  const chart = addChart(copy);
  const refusal = store.add('analytics', chart.id);
  if (refusal) return false;
  if (target) store.moveTo(`analytics:${chart.id}` as SlotId, target);
  layoutEditor.revision++;
  return true;
}

const GRID_ROOT: Record<string, string> = { home: '#launchpad-screen', terminal: '#terminal-grid', warroom: '#warroom-screen' };

export function addPanelWidget(kind: string, target?: DropTarget | null, title: string = kind): boolean {
  const store = live();
  const tail = panels().tail(kind);
  if (!store || tail === undefined) return false;
  const slot = `${kind}:${tail}` as SlotId;
  if (store.state.layout.rows.some((row) => row.slots.some((held) => held.id === slot || held.id.startsWith(`${kind}:`)))) {
    refusePlacement(t('layout_editor.dupe.here', { title }));
    return false;
  }
  if (store.state.layout.hidden.includes(slot)) store.show(slot);
  else if (store.add(kind as InstanceKind, tail)) {
    refusePlacement(t('layout_editor.dupe.here', { title }));
    return false;
  }
  if (target) store.moveTo(slot, target);
  const width = document.querySelector(`${GRID_ROOT[layoutEditor.page ?? 'home'] ?? ''} .oc-cellslot`)?.parentElement?.clientWidth ?? 0;
  if (width > 0) store.setCellSize(slot, panels().fit(kind), width, GUTTER);
  layoutEditor.revision++;
  return true;
}

export function addGalleryPreset(preset: Preset): boolean {
  const store = live();
  if (!store) return false;
  const chart = addChart(presetConfig(preset));
  const slot = `analytics:${chart.id}` as SlotId;
  if (store.add('analytics', chart.id)) return false;
  const target = galleryTarget(store.state.layout, slot, layoutEditor.focusSlot, preset.size);
  if (target) store.moveTo(slot, target);
  layoutEditor.revision++;
  return true;
}

export function changeAnalyticsConfig(chart: ChartConfig): boolean {
  saveChartSettings(chart);
  if (live()) {
    void flushChartView(chart.id);
    layoutEditor.revision++;
  }
  return true;
}

export function hideAnalyticsWidget(id: SlotId): boolean {
  const store = live();
  if (!store || !id.startsWith('analytics:')) return false;
  const before = store.state.layout;
  store.hide(id);
  if (before === store.state.layout) return false;
  layoutEditor.revision++;
  return true;
}

export function restoreAnalyticsWidget(id: SlotId, target?: DropTarget | null): boolean {
  const store = live();
  if (!store || !id.startsWith('analytics:')) return false;
  if (store.state.layout.hidden.includes(id)) store.show(id);
  else if (store.add('analytics', id.slice('analytics:'.length))) return false;
  if (target) store.moveTo(id, target);
  layoutEditor.revision++;
  return true;
}

export function changeBoard(act: () => boolean): boolean {
  if (layoutEditor.active && editing) flushSave(editing.store.page, editing.store.session || undefined);
  const changed = act();
  if (layoutEditor.active) layoutEditor.revision += 1;
  return changed;
}

export const layoutEditorBridge = {
  toggle: toggleLayoutEditor,
  active: (): boolean => layoutEditor.active,
  available: (): boolean => layoutEditor.active || editablePage() !== null,
};
