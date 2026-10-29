import { categoryKey } from '../../layout-editor/drawer-model';
import { suggestedSizes } from '../fits';
import { declaredGlanceHeight } from '../glance-declarations';
import { sizeNameKey, type WidgetSizeName } from '../named-sizes';
import type { WidgetManifest } from '../types';
import { panels } from '../../engine/plugin-kinds';

export interface InfoLine {
  key: string;
  params?: Record<string, unknown>;
}

export interface WidgetInfo {
  id: string;
  titleKey: string;
  icon: string;
  iconTone: string;
  version: string;
  about: InfoLine;
  data: InfoLine;
  categoryKey: string;
  typeKey: string;
  sizes: InfoLine[];
  sizeNames: WidgetSizeName[];
  instancingKey: string;
}

export function infoSuffix(id: string): string {
  return id.startsWith('core.') ? id.slice('core.'.length) : id;
}

export function infoKeys(id: string): { about: string; data: string } {
  return panels().info(id) ?? { about: `widgets.info.about.${infoSuffix(id)}`, data: `widgets.info.data.${infoSuffix(id)}` };
}

export function widgetSizeNames(manifest: WidgetManifest): WidgetSizeName[] {
  const grid = suggestedSizes(manifest.fits).map((size) => size.name);
  return declaredGlanceHeight(manifest.id) !== null ? ['glance', ...grid] : grid;
}

export function widgetInfo(manifest: WidgetManifest): WidgetInfo {
  const keys = infoKeys(manifest.id);
  const { fits } = manifest;
  const sizeNames = widgetSizeNames(manifest);
  const sizes = [
    ...sizeNames.map((name): InfoLine => ({ key: sizeNameKey(name) })),
    { key: fits.anySize ? 'widgets.info.size_any' : 'widgets.info.size_tested_only' },
  ];
  return {
    id: manifest.id,
    titleKey: manifest.titleKey,
    icon: manifest.icon,
    iconTone: manifest.iconTone,
    version: manifest.version,
    about: { key: keys.about },
    data: { key: keys.data },
    categoryKey: categoryKey(manifest.category),
    typeKey: `widgets.type.${manifest.type}`,
    sizes,
    sizeNames,
    instancingKey: `widgets.info.instancing.${manifest.instancing}`,
  };
}
