import type { SlotId } from '../engine/types';
import { allManifests, manifestById } from './core-manifests';
import type { WidgetManifest } from './types';
import { cellManifestFor, isScopeSwitch, viewOfPlacement, viewWidgetId } from './views';

export interface ResolvedPlacement {
  manifest: WidgetManifest;
  cell: WidgetManifest;
  slot: SlotId;
  family: boolean;
  iconWidget: string;
  scopeSwitch: boolean;
  view: string | null;
  target: string | null;
  instance: string | null;
}

export interface PlacementRef {
  widget: string | WidgetManifest;
  view?: string | null;
  target?: string | null;
  instance?: string | null;
}

export function resolvePlacement(ref: PlacementRef): ResolvedPlacement | null {
  const manifest = typeof ref.widget === 'string' ? manifestById(ref.widget) : ref.widget;
  if (!manifest) return null;
  const cell = cellManifestFor(manifest, ref.view, allManifests());
  const target = ref.target ?? null;
  const base = cell.id.slice('core.'.length);
  return {
    manifest,
    cell,
    slot: (target ? `${base}:${target}` : base) as SlotId,
    family: cell.instancing !== 'singleton',
    iconWidget: viewWidgetId(manifest, ref.view),
    scopeSwitch: isScopeSwitch(manifest),
    view: viewOfPlacement(manifest, ref.view)?.id ?? null,
    target,
    instance: ref.instance ?? null,
  };
}
