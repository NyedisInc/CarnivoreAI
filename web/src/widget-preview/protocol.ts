/* the widgets page */

export const PREVIEW_META_NAME = 'carnivore-widget-preview';

export const PREVIEW_PORT_MESSAGE = 'carnivore-widget-preview:port';

export type PreviewMode = 'sample' | 'real';

export interface PreviewConfig {
  key: string;
  zone: 'home' | 'drawer';
  size: { name: string; w: number; h: number };
  mode: PreviewMode;
  theme: string | null;
}

export interface PreviewRequest {
  id: number;
  path: string;
}

export type PreviewAnswer =
  | { id: number; ok: true; body: unknown }
  | { id: number; ok: false; status: number; detail: string };

export const PREVIEW_CLASSIC_SCRIPTS: readonly string[] = [
  '/static/js/api.js',
  '/static/js/module-loader.js',
  '/static/js/module-families.js',
  '/static/js/markdown-lite.js',
  '/static/js/modal-stack.js',
  '/static/js/modal-ring.js',
  '/static/js/status-led.js',
  '/static/js/agent-family-icon.js',
  '/static/js/ui-flags.js',
  '/static/js/session-status-ui.js',
  '/static/js/config-editor-loader.js',
];

export const PREVIEW_STYLESHEETS: readonly string[] = [
  '/static/css/layers.css',
  '/static/css/styles.css',
  '/static/css/scrollbars.css',
  '/static/css/subagent-count.css',
  '/static/css/config-editor.css',
  '/static/dist/widget-preview.css',
];

export const PREVIEW_SCRIPT = '/static/dist/widget-preview.js';

export function readPreviewConfig(doc: Document): PreviewConfig | null {
  const raw = doc.querySelector(`meta[name="${PREVIEW_META_NAME}"]`)?.getAttribute('content');
  if (!raw) return null;
  try {
    const parsed = JSON.parse(raw) as Partial<PreviewConfig>;
    if (typeof parsed.key !== 'string' || !parsed.size || (parsed.mode !== 'sample' && parsed.mode !== 'real')) return null;
    return parsed as PreviewConfig;
  } catch (error) {
    console.warn('[widget-preview] unreadable config', error);
    return null;
  }
}

export function escapeAttribute(value: string): string {
  return value.replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

export function previewDocument(config: PreviewConfig): string {
  const links = PREVIEW_STYLESHEETS.map((href) => `<link rel="stylesheet" href="${escapeAttribute(href)}">`).join('');
  return (
    '<!DOCTYPE html><html lang="en" data-widget-preview=""><head><meta charset="UTF-8">' +
    `<meta name="${PREVIEW_META_NAME}" content="${escapeAttribute(JSON.stringify(config))}">` +
    links +
    '</head><body class="wpv-body"><div id="widget-preview"></div>' +
    '<div class="modal-overlay config-editor-picker-overlay" id="config-editor-overlay" hidden data-modal="config-picker">' +
    '<div class="config-editor-picker-content" role="dialog" aria-modal="true" aria-label="files">' +
    '<div class="config-editor-header" id="config-editor-header"></div>' +
    '<div class="modal-body config-editor-body"><div id="config-editor-tree" class="config-editor-tree"></div></div>' +
    '</div></div>' +
    `<script type="module" src="${escapeAttribute(PREVIEW_SCRIPT)}"></script></body></html>`
  );
}
