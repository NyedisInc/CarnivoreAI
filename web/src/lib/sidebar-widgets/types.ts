import type { Component } from 'svelte';

export type SidebarWidgetKind = 'system' | 'registered';

export type SidebarSurface = 'root' | 'strip' | 'flyout';

export type SidebarTint = `--oc-${string}`;

export type SidebarPartPainter = 'drawer-list';

export interface MountedPart {
  component: Component<Record<string, never>, Record<string, unknown>>;
}

export interface PaintedPart {
  paintedBy: SidebarPartPainter;
}

export interface TabBodyPart {
  tab: string;
}

export type SidebarPart = MountedPart | PaintedPart | TabBodyPart;

export interface SidebarWidget {
  id: string;
  titleKey: string;
  icon: string;
  kind: SidebarWidgetKind;
  surface: SidebarSurface;
  tint?: SidebarTint;
  dismissOnOutsideClick?: boolean;
  order: number;
  present?: () => boolean;
  hiddenUntilData?: () => number | boolean;
  badge?: () => number | null;
  tab?: string;
  opensFromTab?: boolean;
  close?: () => void;
  action?: () => void;
  parts: Readonly<Record<string, SidebarPart>>;
}

export type SidebarRefusal =
  | 'duplicate-id'
  | 'tint-required'
  | 'tint-not-allowed'
  | 'outside-click-not-allowed'
  | 'tab-body-not-allowed'
  | 'no-parts';

export type SidebarRegistration = { ok: true } | { ok: false; reason: SidebarRefusal };

export function isMountedPart(part: SidebarPart): part is MountedPart {
  return 'component' in part;
}

export function isTabBodyPart(part: SidebarPart): part is TabBodyPart {
  return 'tab' in part;
}
