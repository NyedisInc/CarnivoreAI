/* something else */

export interface ThumbnailSource {
  feature: string;
  file: string;
}

export const WIDGET_THUMBNAILS: Readonly<Record<string, ThumbnailSource>> = Object.freeze({
  'core.keep-awake': { feature: 'keep-awake-widget', file: 'widget.png' },
  'core.scheduled-tasks': { feature: 'scheduled-tasks-widget', file: 'widget.png' },
  'core.ledger': { feature: 'provider-ledger', file: 'panel.png' },
  ...Object.fromEntries(
    [
      'running-sessions',
      'closed-sessions',
      'projects',
      'skills',
      'plugins',
      'themes',
      'activity-log',
      'notes',
      'files',
    ].map((cell) => [`core.${cell}`, { feature: 'widget-thumbnails', file: `${cell}.png` }]),
  ),
});

export function thumbnailFor(widgetId: string): ThumbnailSource | null {
  return WIDGET_THUMBNAILS[widgetId] ?? null;
}

const PLUGIN_PREVIEWS = new Map<string, string>();

export function setPluginPreview(widgetId: string, path: string | undefined): void {
  if (path) PLUGIN_PREVIEWS.set(widgetId, path);
  else PLUGIN_PREVIEWS.delete(widgetId);
}

export function pluginPreviewFor(widgetId: string): string | null {
  return PLUGIN_PREVIEWS.get(widgetId) ?? null;
}
