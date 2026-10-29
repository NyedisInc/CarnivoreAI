import type { Component } from 'svelte';
import type { WidgetSettingsSchema } from '../../opscenter/widgets/types';
import type { PlacementOptionValue } from './glance-model';
import { declaredGlanceHeight } from '../../opscenter/widgets/glance-declarations';
import { GLANCE_ROW_PADDING_PX } from '../../opscenter/widgets/standard-sizes';

export const GLANCE_TILE_WIDTH_PX = 64;
export const GLANCE_TILE_HEIGHT_PX = 36;

export const GLANCE_ROW_HEIGHT_PX = GLANCE_TILE_HEIGHT_PX + GLANCE_ROW_PADDING_PX;

export interface GlanceTile<T = unknown> {
  key: string;
  data: T;
}

export interface GlanceTileProps<T = unknown> {
  data: T;
  onopen: () => void;
}

export type PlacementOptions = Readonly<Record<string, PlacementOptionValue>>;

export interface GlancePlacementOptions {
  schema: WidgetSettingsSchema;
  optionLabel?: (key: string, option: string) => string | undefined;
}

export interface GlanceRenderer<T = unknown> {
  tiles(options: PlacementOptions): readonly GlanceTile<T>[];
  /* the glance area */
  options?: () => GlancePlacementOptions;
  component: Component<GlanceTileProps<T>>;
}

export interface GlanceSpec<T = unknown> extends GlanceRenderer<T> {
  height: number;
}

export class GlanceRegistry {
  #renderers = new Map<string, GlanceRenderer<never>>();
  #heightOf: (widget: string) => number | null;

  constructor(heightOf: (widget: string) => number | null = declaredGlanceHeight) {
    this.#heightOf = heightOf;
  }

  register<T>(widget: string, renderer: GlanceRenderer<T>): boolean {
    if (this.#heightOf(widget) === null) {
      console.warn('Glance: refused a renderer for a widget that declares no glance', { widget });
      return false;
    }
    if (this.#renderers.has(widget)) {
      console.warn('Glance: refused a second renderer', { widget });
      return false;
    }
    this.#renderers.set(widget, renderer as unknown as GlanceRenderer<never>);
    return true;
  }

  get(widget: string): GlanceSpec | null {
    const renderer = this.#renderers.get(widget);
    const height = this.#heightOf(widget);
    return renderer && height !== null ? { ...(renderer as unknown as GlanceRenderer), height } : null;
  }
}

export const glances = new GlanceRegistry();

export function registerGlance<T>(widget: string, renderer: GlanceRenderer<T>): boolean {
  return glances.register(widget, renderer);
}

export function repeatableInGlance(widget: string): boolean {
  return !!glances.get(widget)?.options;
}

export function glanceFor(widget: string): GlanceSpec | null {
  return glances.get(widget);
}
