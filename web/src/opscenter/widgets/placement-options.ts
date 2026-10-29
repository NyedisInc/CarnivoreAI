import type { WidgetSettingsSchema } from './types';

export type PlacementOptionValue = boolean | number | string;

export type PlacementOptions = Readonly<Record<string, PlacementOptionValue>>;

export const PLACEMENT_OPTION_WIDGETS: ReadonlySet<string> = new Set(['core.questions', 'core.task-list', 'core.session-contents']);

export const SINGLE_COPY_OPTION_WIDGETS: ReadonlySet<string> = new Set(['core.running-sessions']);

export interface PlacementHead {
  icon: string;
  title: string;
}

export interface PlacementOptionsDeclaration {
  schema(): WidgetSettingsSchema;
  head?(options: PlacementOptions): PlacementHead | null;
  menuHeadingKey?: string;
  isRetiredKey?(key: string): boolean;
}

const declarations = new Map<string, PlacementOptionsDeclaration>();

export function hasPlacementOptions(widgetId: string): boolean {
  return PLACEMENT_OPTION_WIDGETS.has(widgetId) || SINGLE_COPY_OPTION_WIDGETS.has(widgetId);
}

export function hasRepeatableOptions(widgetId: string): boolean {
  return PLACEMENT_OPTION_WIDGETS.has(widgetId);
}

export function registerPlacementOptions(widgetId: string, declaration: PlacementOptionsDeclaration): void {
  declarations.set(widgetId, declaration);
}

export function placementOptionsFor(widgetId: string): PlacementOptionsDeclaration | undefined {
  return declarations.get(widgetId);
}

export function isRetiredPlacementKey(widgetId: string, key: string): boolean {
  return declarations.get(widgetId)?.isRetiredKey?.(key) ?? false;
}

export function placementHead(widgetId: string, options: PlacementOptions | undefined): PlacementHead | null {
  return declarations.get(widgetId)?.head?.(options ?? {}) ?? null;
}
