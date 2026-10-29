/* the widgets page */
import { harnessWidgets, type HarnessWidget } from '../../widget-harness/catalog';
import { NEEDS_BOUND_SESSION } from '../../widget-harness/bound-session';
import { widgetSizeNames } from '../../opscenter/widgets/info/widget-info';
import type { WidgetSizeName } from '../../opscenter/widgets/named-sizes';
import type { WidgetManifest } from '../../opscenter/widgets/types';

export interface PreviewSize {
  name: WidgetSizeName;
  key: string;
  zone: 'home' | 'drawer';
  w: number;
  h: number;
}

export function previewEntry(manifestId: string): HarnessWidget | undefined {
  return harnessWidgets().find((one) => one.manifest === manifestId);
}

export function previewSizes(manifest: WidgetManifest): PreviewSize[] {
  const entry = previewEntry(manifest.id);
  if (!entry) return [];
  const out: PreviewSize[] = [];
  for (const name of widgetSizeNames(manifest)) {
    const zone = name === 'glance' ? 'drawer' : 'home';
    const size = entry.sizes[zone]?.find((one) => one.name === name);
    if (size && size.h !== null) out.push({ name, key: entry.key, zone, w: size.w, h: size.h });
  }
  return out;
}

export function realPreviewAvailable(manifest: WidgetManifest): boolean {
  return manifest.instancing === 'singleton' && !NEEDS_BOUND_SESSION.has(manifest.id);
}

export const HERO_MAX_SCALE = 4;

export function heroHeight(box: Pick<PreviewSize, 'name' | 'w' | 'h'> | null, paneWidth: number): number {
  if (!box) return 168;
  if (box.name === 'glance') return 168;
  const s = Math.min(1, (paneWidth - 32) / box.w);
  return Math.round(Math.min(380, box.h * s + 16 + 36 + 8));
}
