import type { Component } from 'svelte';

export type WidgetAreaState = 'full' | 'glance' | 'closed';

export const WIDGET_AREA_STATES: readonly WidgetAreaState[] = ['closed', 'glance', 'full'];

export type TabTone = 'default' | 'question';

export interface DynamicTabDef {
  id: string;
  labelKey: string;
  nameKey?: string;
  icon: string;
  order: number;
  persist: boolean;
  present?: () => boolean;
  focusOnAppear?: boolean;
  onAppear?: () => void;
  open?: () => boolean;
  close?: () => void;
  railAction?: () => void;
  /* the main area is as it was */
  mainView?: import('svelte').Component;
  mainViewOnPhone?: boolean;
  badge?: () => number | null;
  tone?: TabTone | (() => TabTone);
  widgetArea: WidgetAreaState;
  popout?: boolean;
  popoutParams?: () => Record<string, string>;
  popoutMulti?: boolean;
  body: { containers: readonly string[] } | { component: Component; titleKey?: string; titleActions?: Component<{ popout?: boolean }> };
}

export function toneOf(def: Pick<DynamicTabDef, 'tone'>): TabTone {
  const tone = def.tone;
  return typeof tone === 'function' ? tone() : (tone ?? 'default');
}
