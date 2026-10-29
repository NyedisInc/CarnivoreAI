
export interface HostRule {
  name: string;
  pattern: RegExp;
  owners: readonly string[];
  within?: readonly string[];
  files?: RegExp;
}

export interface HostSource {
  path: string;
  text: string;
}

export interface HostFinding {
  path: string;
  rule: string;
}

export const DIALOG_OPT_OUT: Readonly<Record<string, string>> = {
  'lib/browser/BrowserView.svelte': 'an in-flow bar inside one browser widget that holds the remote page\'s own alert, confirm or prompt; it is part of that widget\'s layout, not an overlay, and a global modal would cover widgets that did not ask',
  'lib/help/MediaLightbox.svelte': 'a floating, draggable, resizable window with its own remembered geometry (#1849); ModalShell\'s centered chassis and tab ring do not fit it',
  'lib/session-skills/SessionSkillsPanel.svelte': 'a docked drawer panel (`aria-modal="false"`) that sits beside the terminal; the Escape guards read its `role="dialog"` as the floating layer that owns Escape, so the role stays',
  'widget-preview/protocol.ts': 'an HTML string for the preview iframe (`srcdoc`), the files picker\'s static markup that the legacy panel adopts; there is no Svelte component in an iframe document to draw a frame with',
};

export const HOST_RULES: readonly HostRule[] = [
  { name: 'core-manifest-read', pattern: /CORE_MANIFESTS\[/, owners: ['opscenter/widgets/core-manifests.ts'] },
  { name: 'cell-manifest-core-table', pattern: /cellManifestFor\([^)]*CORE_MANIFESTS/, owners: [] },
  { name: 'bar-handle', pattern: /<BarHandle\b/, owners: ['lib/zone-shell/'] },
  { name: 'bar-pin', pattern: /<BarPin[\s/>]/, owners: ['lib/session-rail/SessionRail.svelte', 'lib/sidebar-widgets/SidebarRailShell.svelte', 'style-guide/specimens/BarVisibilityDemo.svelte', 'lib/drawer-tabs/DrawerMenu.svelte'] },
  {
    name: 'bar-pin-action',
    pattern: /toggleBarPin\(|pinStripNode\(|pinBarNode\(/,
    owners: ['lib/widget-bars/bar-pin-action.ts', 'lib/widget-bars/BarPin.svelte', 'lib/widget-menu/bar-menu.ts', 'lib/widget-menu/rail-menu.ts', 'opscenter/layout-editor/empty-space-menu.svelte.ts', 'lib/sidebar-widgets/rail-menu.svelte.ts'],
  },
  { name: 'peek-core', pattern: /createPeekCore\(/, owners: ['lib/widget-bars/peek-core.svelte.ts', 'lib/widget-bars/bar-visibility.svelte.ts', 'lib/sidebar-widgets/rail-visibility.svelte.ts'] },
  { name: 'build-widget-menu', pattern: /buildWidgetMenu\(/, owners: ['lib/widget-menu/model.ts', 'lib/item-menu/menus/widget.ts'] },
  { name: 'active-scope', pattern: /activeScopeFor\(/, owners: ['lib/zone-shell/', 'opscenter/CellHost.svelte', 'opscenter/widgets/active-scope.ts'] },
  { name: 'frame-header', pattern: /provideFrameHeader\(|adoptFrameHeader\(/, owners: ['lib/zone-shell/', 'opscenter/shell/frame-header.svelte.ts'] },
  { name: 'tab-pane', pattern: /provideTabPane\(/, owners: ['lib/zone-shell/', 'opscenter/shell/frame-header.svelte.ts'] },
  { name: 'tab-pane-component', pattern: /(?<![A-Za-z])TabPane\.svelte/, owners: [] },
  // the shared one
  { name: 'intersection-observer', pattern: /\bnew\s+(?:window\.|globalThis\.)?IntersectionObserver\b/, owners: [] },
  { name: 'document-keydown', pattern: /\b(?:document|doc|window|globalThis)\.addEventListener\(\s*['"]keydown['"]/, owners: ['lib/widget-bars/strip-escape.svelte.ts', 'lib/widget-bars/bar-drag.svelte.ts'], within: ['lib/sidebar-widgets/', 'lib/session-rail/', 'lib/mini-rail/', 'lib/widget-bars/'] },
  { name: 'widget-tab-parse', pattern: /['"`]widget:['"`]|startsWith\(\s*['"`]widget:/, owners: ['opscenter/engine/widget-tabs.ts'] },
  { name: 'drawer-mount', pattern: /\bmountPanel\(\s*(?:DRAWER_TABBODY_ID|DRAWER_AREA_BAR_ID|DRAWER_LEDGER_ID|DRAWER_MINI_RAIL_ID|['"]session-sidebar-(?:tabbody|area-bar|ledger|rail)['"])/, owners: ['lib/drawer-layout/'] },
  { name: 'badge-class', pattern: /sbr-rail__badge|mr-key-badge|\brail__badge\b|RailKeyBadge/, owners: ['lib/zone-shell/host-scan.ts'] },
  {
    name: 'key-button',
    pattern: /\bclass=["'][^"']*?(?<![\w-])(?:rail__key|sbr-rail__btn|mr-claw|oc-tab|ltab__name|dz-glance|oc-topbar-drawer|oc-topbar-brand|dwl-chrome-key|oc-tab-x|sbr-rail__close)(?![\w-])|\sdata-(?:phone-tabs-claw|rail-settings)(?=[\s>=])/,
    owners: ['lib/zone-shell/TabKey.svelte'],
  },
  { name: 'menu-key-literal', pattern: /['"`](?:ContextMenu|F10)['"`]/, owners: ['lib/zone-shell/key-nav.ts'] },
  { name: 'page-tabs', pattern: /\brole=["']tablist["']/, owners: ['opscenter/ui/Tabs.svelte', 'opscenter/shell/TabStrip.svelte'] },
  {
    name: 'dialog-frame',
    pattern: /<[a-z][\w-]*\s[^<]*?\s(?:role=["'](?:alert)?dialog["']|aria-modal=)/,
    owners: ['lib/launchpad/ModalShell.svelte', 'lib/dialog-frame/AnchoredPopup.svelte', 'lib/elite/', ...Object.keys(DIALOG_OPT_OUT)],
  },
  {
    name: 'page-row-menu',
    pattern: /\boncontextmenu=|<(?:SessionKebab|RowMenu)\b|\bisMenuKey\(/,
    owners: ['lib/item-menu/'],
    within: ['lib/sessions-page/', 'lib/deepsearch/', 'lib/sessions-search/'],
  },
];

export interface ZoneLayerRule {
  name: string;
  pattern: RegExp;
  scope: 'shell' | 'both';
}

export const ZONE_LAYER_RULES: readonly ZoneLayerRule[] = [
  { name: 'data-fetch', pattern: /(?<![\w.])(?:fetch|authFetch)\s*\(/, scope: 'both' },
  { name: 'data-interval', pattern: /(?<![\w.])setInterval\s*\(/, scope: 'both' },
  { name: 'data-socket', pattern: /\bnew\s+WebSocket\b/, scope: 'both' },
  { name: 'frame-wait', pattern: /(?<![\w.])requestAnimationFrame\s*\(/, scope: 'shell' },
];

export const ZONE_LAYER_FILES: readonly string[] = [
  'lib/session-rail/SessionRail.svelte',
  'lib/session-rail/RailSlideout.svelte',
  'lib/sidebar-widgets/SidebarRailShell.svelte',
  'lib/sidebar-widgets/SidebarRail.svelte',
  'lib/sidebar-widgets/SidebarFlyoutHost.svelte',
  'lib/mini-rail/MiniRail.svelte',
  'opscenter/cells/terminal-group/Cell.svelte',
  'lib/sidebar-shell/SidebarList.svelte',
  'opscenter/CellHost.svelte',
  'opscenter/shell/CellFrame.svelte',
  'opscenter/shell/grid-zone.ts',
  'opscenter/engine/CellMenu.svelte',
];

export const ZONE_LAYER_DIRS: readonly string[] = ['lib/session-list/', 'lib/drawer-layout/', 'lib/drawer-zone/'];

export function withoutComments(text: string): string {
  return text.replace(/<!--[\s\S]*?-->/g, '').replace(/\/\*[\s\S]*?\*\//g, '').replace(/(^|\s)\/\/.*$/gm, '$1');
}

export function scanHosts(sources: readonly HostSource[]): HostFinding[] {
  return scanRules(HOST_RULES, sources);
}

export function scanRules(rules: readonly HostRule[], sources: readonly HostSource[]): HostFinding[] {
  const found: HostFinding[] = [];
  for (const source of sources) {
    const code = withoutComments(source.text);
    for (const rule of rules) {
      if (rule.owners.some((owner) => source.path.includes(owner))) continue;
      if (rule.within && !rule.within.some((prefix) => source.path.startsWith(prefix))) continue;
      if (rule.files && !rule.files.test(source.path)) continue;
      if (rule.pattern.test(code)) found.push({ path: source.path, rule: rule.name });
    }
  }
  return found.sort((a, b) => `${a.path}:${a.rule}`.localeCompare(`${b.path}:${b.rule}`));
}

export function scanZoneLayer(sources: readonly HostSource[]): HostFinding[] {
  const found: HostFinding[] = [];
  for (const source of sources) {
    const inShell = source.path.startsWith('lib/zone-shell/');
    if (!inShell && !ZONE_LAYER_FILES.includes(source.path) && !ZONE_LAYER_DIRS.some((dir) => source.path.startsWith(dir))) continue;
    const code = withoutComments(source.text);
    for (const rule of ZONE_LAYER_RULES) {
      if (rule.scope === 'shell' && !inShell) continue;
      if (rule.pattern.test(code)) found.push({ path: source.path, rule: rule.name });
    }
  }
  return found.sort((a, b) => `${a.path}:${a.rule}`.localeCompare(`${b.path}:${b.rule}`));
}
