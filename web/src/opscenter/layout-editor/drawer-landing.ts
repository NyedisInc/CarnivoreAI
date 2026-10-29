import type { LayoutStore } from '../engine/layout.svelte';
import type { WidgetManifest } from '../widgets/types';
import { t } from '../../lib/i18n/index.svelte';
import { repeatableInGlance } from '../../lib/drawer-zone/glance';
import { FAMILY_TARGET_OPTION } from '../../lib/drawer-zone/glance-model';
import { drawerZone } from '../../lib/drawer-zone/zone-store.svelte';
import { placeInRail } from '../../lib/session-rail/rail-store.svelte';
import type { RailEdge } from '../../lib/session-rail/rail-model';
import type { RailSpot } from '../../lib/session-rail/rail-sections';
import { addChart } from '../cells/analytics/state.svelte';
import type { CarryTarget } from './drawer-carry';
import { isPanelRow, type GroupRow } from './drawer-groups';
import { addAnalyticsWidget, addPanelWidget, dropWidget } from './editor.svelte';
import { refusePlacement } from '../widgets/chrome/refusal-toast.svelte';
import { askDuplicate, duplicateKind } from './duplicate-prompt.svelte';

export function landRow(store: LayoutStore, row: GroupRow, target: CarryTarget, pointer: { x: number; y: number }): void {
  if (isPanelRow(row)) {
    if (target.area !== 'surface') refusePlacement(t('layout_editor.refuse.panel_surface_only'));
    else if (addPanelWidget(row.manifest.id, target.target, row.title)) store.announce(t('layout_editor.announce.added', { title: row.title }));
    return;
  }
  if (row.family) {
    landFamilyCopy(store, row, target);
    return;
  }
  const inGlance = drawerZone.glance.find((placement) => placement.widget === row.manifest.id)?.id ?? null;
  const kind = duplicateKind(target, {
    family: false,
    onScreen: row.state === 'placed',
    inGlance,
    repeatable: repeatableInGlance(row.manifest.id),
  });
  if (kind) {
    askDuplicate({
      kind,
      title: row.title,
      ...pointer,
      onCopy: () => landNow(store, row, target),
      onMove: () => moveExisting(row, target, inGlance),
    });
    return;
  }
  landNow(store, row, target);
}

export function moveExisting(row: GroupRow, target: CarryTarget, inGlance: string | null): void {
  if (target.area === 'surface') {
    if (row.cell) void dropWidget(row.cell, target.target);
  } else if (target.area === 'zone') {
    drawerZone.move(target.moves ?? row.manifest.id, target.index);
  } else if (target.area === 'rail') {
    placeInRail(target.edge, row.manifest.id, target.spot);
  } else {
    const id = target.moves ?? inGlance;
    if (id) drawerZone.moveGlance(id, target.index);
  }
}

export function landNow(store: LayoutStore, row: GroupRow, target: CarryTarget): void {
  if (target.area === 'surface') {
    if (row.cell) void dropWidget(row.cell, target.target);
  } else if (target.area === 'zone') {
    if (target.moves) drawerZone.move(target.moves, target.index);
    else addToZone(store, row.manifest, target.index);
  } else if (target.area === 'rail') {
    addToRail(store, target.edge, row.manifest.id, row.title, target.spot);
  } else if (target.moves) {
    drawerZone.moveGlance(target.moves, target.index);
  } else if (drawerZone.addGlance(row.manifest.id, repeatableInGlance(row.manifest.id), target.index)) {
    store.announce(t('layout_editor.announce.glance_added', { title: row.title }));
  }
}

export function landFamilyCopy(store: LayoutStore, row: GroupRow, target: CarryTarget): void {
  if (target.area === 'surface') {
    if (addAnalyticsWidget(undefined, target.target)) store.announce(t('layout_editor.announce.added', { title: row.title }));
    return;
  }
  const chart = addChart();
  if (target.area === 'rail') {
    addToRail(store, target.edge, row.manifest.id, row.title, target.spot, chart.id);
  } else if (target.area === 'zone') {
    if (drawerZone.add(row.manifest.id, target.index, chart.id)) store.announce(t('layout_editor.announce.zone_added', { title: row.title }));
  } else if (drawerZone.addGlance(row.manifest.id, true, target.index, { [FAMILY_TARGET_OPTION]: chart.id })) {
    store.announce(t('layout_editor.announce.glance_added', { title: row.title }));
  }
}

export function addToZone(store: LayoutStore, manifest: WidgetManifest, index?: number): void {
  if (drawerZone.add(manifest.id, index)) store.announce(t('layout_editor.announce.zone_added', { title: t(manifest.titleKey) }));
}

export function addToRail(store: LayoutStore, edge: RailEdge, widget: string, title: string, spot?: RailSpot, target?: string): boolean {
  const added = placeInRail(edge, widget, spot, target);
  if (added) store.announce(t('layout_editor.announce.rail_added', { title }));
  return added;
}
