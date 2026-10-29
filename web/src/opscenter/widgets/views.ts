import type { WidgetManifest, WidgetView } from './types';

export type ManifestTable = Readonly<Record<string, WidgetManifest>>;

export interface PlacementIdentity {
  widget: string;
  view?: string;
}

export function viewsOf(manifest: Pick<WidgetManifest, 'views'> | undefined): readonly WidgetView[] {
  const views = manifest?.views;
  return views && views.length > 1 ? views : [];
}

export function hasViews(manifest: Pick<WidgetManifest, 'views'> | undefined): boolean {
  return viewsOf(manifest).length > 0;
}

export function viewOfPlacement(manifest: Pick<WidgetManifest, 'views'> | undefined, stored: string | null | undefined): WidgetView | null {
  const views = viewsOf(manifest);
  if (views.length === 0) return null;
  return views.find((view) => view.id === stored) ?? (views[0] as WidgetView);
}

export function cellManifestFor(manifest: WidgetManifest, stored: string | null | undefined, table: ManifestTable): WidgetManifest {
  const view = viewOfPlacement(manifest, stored);
  return (view && table[view.widget]) || manifest;
}

export function viewWidgetId(manifest: Pick<WidgetManifest, 'id' | 'views'>, stored: string | null | undefined): string {
  return viewOfPlacement(manifest, stored)?.widget ?? manifest.id;
}

export function isViewCell(manifest: Pick<WidgetManifest, 'viewOf'> | undefined): boolean {
  return !!manifest?.viewOf;
}

export function mergedIds(table: ManifestTable): Readonly<Record<string, { widget: string; view: string }>> {
  const out: Record<string, { widget: string; view: string }> = {};
  for (const manifest of Object.values(table)) {
    for (const view of viewsOf(manifest)) {
      if (view.widget !== manifest.id) out[view.widget] = { widget: manifest.id, view: view.id };
    }
  }
  return out;
}

export function mergePlacement(placement: PlacementIdentity, merged: Readonly<Record<string, { widget: string; view: string }>>): PlacementIdentity {
  const hit = merged[placement.widget];
  return hit ? { widget: hit.widget, view: hit.view } : placement;
}

export function drawingIds(manifest: Pick<WidgetManifest, 'id' | 'views'>): string[] {
  return [...new Set([manifest.id, ...viewsOf(manifest).map((view) => view.widget)])];
}

export const SCOPE_VIEW_IDS = ['session', 'all'] as const;

export function isScopeSwitch(manifest: Pick<WidgetManifest, 'views'> | undefined): boolean {
  const ids = viewsOf(manifest).map((view) => view.id);
  return ids.length === SCOPE_VIEW_IDS.length && SCOPE_VIEW_IDS.every((id, at) => ids[at] === id);
}
