import { declaredGlanceHeight } from '../glance-declarations';
import type { WidgetManifest } from '../types';
import { widgetInfo, type WidgetInfo } from './widget-info';

export type WidgetPlace = 'dashboard' | 'terminal' | 'sidebar' | 'glance';

export const WIDGET_PLACES: readonly WidgetPlace[] = ['dashboard', 'terminal', 'sidebar', 'glance'];

export interface WidgetMaker {
  kind: 'built-in' | 'plugin';
  vendor: string;
}

export interface WidgetDescription {
  info: WidgetInfo;
  places: WidgetPlace[];
  /* there is nothing */
  options: string[];
  maker: WidgetMaker;
}

export function widgetPlaces(_manifest: WidgetManifest, glanceHeight: number | null): WidgetPlace[] {
  return WIDGET_PLACES.filter((place) => place !== 'glance' || glanceHeight !== null);
}

export function widgetMaker(id: string): WidgetMaker {
  const vendor = id.includes('.') ? id.slice(0, id.indexOf('.')) : id;
  return { kind: vendor === 'core' ? 'built-in' : 'plugin', vendor };
}

export function widgetDescription(
  manifest: WidgetManifest,
  glanceHeight: number | null = declaredGlanceHeight(manifest.id),
): WidgetDescription {
  return {
    info: widgetInfo(manifest),
    places: widgetPlaces(manifest, glanceHeight),
    options: Object.values(manifest.settings?.fields ?? {}).map((field) => field.labelKey),
    maker: widgetMaker(manifest.id),
  };
}
