import { scanRules, type HostFinding, type HostRule, type HostSource } from './host-scan';

const LED_SIGNAL_PROPS = 'unread|startupGate|statusSource|transport|activityHint|parkedSummary|hostOffline|usageLimit';

export const WRAPPER_RULES: readonly HostRule[] = [
  {
    name: 'menu-frame',
    pattern: /(?<!\[)\brole=["']menu["']/,
    owners: ['CascadeMenu.svelte', 'opscenter/cells/terminal-live/TerminalActions.svelte'],
    files: /\.svelte$/,
  },
  { name: 'own-tooltip', pattern: /\brole=["']tooltip["']|\bclass=["'][^"']*?tooltip/, owners: ['lib/tooltip/'] },
  { name: 'interval-anywhere', pattern: /\bsetInterval\(/, owners: ['opscenter/lib/frozen-clock.svelte.ts', 'opscenter/api/poll.svelte.ts'] },
  {
    name: 'flyout-press',
    pattern: /\b(?:pressRail|openFlyout)\(/,
    owners: ['lib/zone-shell/left-rail-zone.svelte.ts', 'lib/sidebar-widgets/flyout.svelte.ts', 'lib/sidebar-widgets/rail-visibility.svelte.ts', 'lib/sidebar-widgets/SidebarFlyoutHost.svelte'],
  },
  { name: 'fetch-in-component', pattern: /(?<![.\w])(?:authFetch|fetch)\(/, owners: [], files: /\.svelte$/ },
  {
    name: 'led-signals',
    pattern: new RegExp(
      '<StatusLed\\b(?:(?!/>)[\\s\\S])*?(?:\\b(?:' + LED_SIGNAL_PROPS + ')=\\{(?!\\s*(?:true|false|null)\\s*\\})|\\{(?:' + LED_SIGNAL_PROPS + ')\\})'
        + '|\\b(?:ledHtmlForStatus|ledAttrsForStatus)\\(|\\bSessionStatusUI\\.dotHtml\\(',
    ),
    owners: ['lib/sessions/SessionFace.svelte', 'lib/StatusLed.svelte', 'lib/status-dot.ts', 'lib/led.ts', 'lib/led-legacy-fixture.ts', 'style-guide/specimens/LedMatrix.svelte'],
  },
];

export function scanWrappers(sources: readonly HostSource[]): HostFinding[] {
  return scanRules(WRAPPER_RULES, sources);
}
