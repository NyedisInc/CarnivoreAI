/* the widget harness page */
import type { LabSize, SidebarView } from '../sdk/widget-lab';
import { DEFAULT_SIDEBAR_VIEW as DEFAULT_VIEW, viewToQuery } from '../sdk/widget-lab';

export const FRAME_PATH = '/static/dist/widget-lab/index.html';

export const FIXTURE_CHOICES = ['data', 'empty', 'stress'] as const;
export type FixtureChoice = (typeof FIXTURE_CHOICES)[number];

export const STAGE_PADDING_PX = 16;

export const FRAME_MIN_WIDTH_PX = 400;
export const FRAME_MIN_HEIGHT_PX = 440;

export const SIDEBAR_WINDOW: Readonly<{ w: number; h: number }> = Object.freeze({ w: 1440, h: 800 });

export interface FrameSpec {
  widget: string;
  host: string;
  size: string;
  theme: string;
  fixture: FixtureChoice;
  scenario: boolean;
  box?: { w: number; h: number | null };
  dock?: 'side' | 'bottom';
  shell?: 'sidebar';
  view?: SidebarView;
  idle?: boolean;
  page?: string;
}

export function frameUrl(spec: FrameSpec): string {
  const query = new URLSearchParams({ widget: spec.widget, zone: spec.host, size: spec.size, theme: spec.theme, fixture: spec.fixture, lab: '1' });
  if (spec.scenario) query.set('scenario', 'wait');
  if (spec.idle) query.set('idle', '1');
  if (spec.dock && spec.host === 'drawer') query.set('dock', spec.dock);
  if (spec.shell === 'sidebar') {
    query.set('shell', 'sidebar');
    for (const [key, value] of Object.entries(viewToQuery(spec.view ?? DEFAULT_VIEW))) query.set(key, value);
  }
  if (spec.box) {
    query.set('w', String(spec.box.w));
    if (spec.box.h !== null) query.set('h', String(spec.box.h));
  }
  return `${spec.page ?? FRAME_PATH}?${query.toString()}`;
}

export function frameWidth(size: LabSize, boxWidth?: number): number {
  return size.viewport < FRAME_MIN_WIDTH_PX && boxWidth === undefined ? size.viewport : Math.max((boxWidth ?? size.w) + 2 * STAGE_PADDING_PX, FRAME_MIN_WIDTH_PX);
}

export const DESKTOP_WINDOW_MIN_PX = 1024;

export function frameWindowWidth(size: LabSize): number {
  if (size.viewport < DESKTOP_WINDOW_MIN_PX) return frameWidth(size);
  return Math.max(size.viewport, DESKTOP_WINDOW_MIN_PX, size.w + 2 * STAGE_PADDING_PX);
}

export function frameHeight(size: LabSize): number {
  return Math.max((size.h ?? 0) + 2 * STAGE_PADDING_PX, FRAME_MIN_HEIGHT_PX);
}
