/* its own sentence */

export const WIDGET_STATUSES = ['ready', 'none', 'loading', 'empty', 'error'] as const;

export type WidgetStatus = (typeof WIDGET_STATUSES)[number];

export function statusKey(status: Exclude<WidgetStatus, 'ready'>): string {
  return `widget.state.${status}`;
}
