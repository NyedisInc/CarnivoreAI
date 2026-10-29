
import type { WidgetManifest } from './types';

export const INSTANCE_SETTINGS_WIDGETS: ReadonlySet<string> = new Set(['core.analytics']);

export function hasInstanceSettings(manifest: Pick<WidgetManifest, 'id' | 'instancing'>): boolean {
  return manifest.instancing === 'per-target' && INSTANCE_SETTINGS_WIDGETS.has(manifest.id);
}
