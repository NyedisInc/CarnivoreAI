import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';
import type { HostFinding, HostSource } from './host-scan';
import { WRAPPER_RULES, scanWrappers } from './wrapper-rules';

const SRC = fileURLToPath(new URL('../..', import.meta.url));

const KNOWN: readonly string[] = [
  'cplugs/crate/ExportDialog.svelte:interval-anywhere',
  'cplugs/crate/ImportDialog.svelte:interval-anywhere',
  'cplugs/huddle/chat/ChatBar.svelte:menu-frame',
  'cplugs/huddle/chat/ChatWidget.svelte:interval-anywhere',
  'cplugs/huddle/style-guide/CharacterBoard.svelte:interval-anywhere',
  'cplugs/huddle/style-guide/ExpressionBoard.svelte:interval-anywhere',
  'cplugs/huddle/swarm/characters/clock.ts:interval-anywhere',
  'cplugs/huddle/task-manager-progress.svelte.ts:interval-anywhere',
  'cplugs/huddle/TaskManagerMove.svelte:menu-frame',
  'cplugs/sdk/tab-flyout.ts:flyout-press',
  'cplugs/share/ShareModal.svelte:interval-anywhere',
  'lib/automations/page-store.svelte.ts:interval-anywhere',
  'lib/background-work/FootWork.svelte:interval-anywhere',
  'lib/computers/ComputersPanel.svelte:interval-anywhere',
  'lib/computers/InviteCard.svelte:interval-anywhere',
  'lib/drawer-tabs/DrawerQuestions.svelte:interval-anywhere',
  'lib/drawer-tabs/menu-rows.ts:flyout-press',
  'lib/drawer/controller.ts:interval-anywhere',
  'lib/elite/engine/boot.ts:interval-anywhere',
  'lib/elite/engine/logo.ts:interval-anywhere',
  'lib/elite/MenuBlock.svelte:interval-anywhere',
  'lib/hosts-page/ShowCodeModal.svelte:interval-anywhere',
  'lib/ledger-drawer/DrawerLedger.svelte:interval-anywhere',
  'lib/listing-push/store.ts:interval-anywhere',
  'lib/live-status/OfflineMarker.svelte:interval-anywhere',
  'lib/mini-rail/MiniRail.svelte:interval-anywhere',
  'lib/notifications/presence.ts:interval-anywhere',
  'lib/perf-overlay/PerfOverlay.svelte:interval-anywhere',
  'lib/pipeline-status/PipelineSquares.svelte:own-tooltip',
  'lib/resource-push/store.ts:interval-anywhere',
  'lib/sessions-page/timeline-lanes.svelte.ts:interval-anywhere',
  'lib/sessions-page/TimelineView.svelte:interval-anywhere',
  'lib/sessions/poller.ts:interval-anywhere',
  'lib/settings-page/PairWindow.svelte:interval-anywhere',
  'lib/settings-page/PhoneLinkPanel.svelte:interval-anywhere',
  'lib/sidebar-widgets/rail-layout.svelte.ts:flyout-press',
  'lib/swarm-board/board-data.svelte.ts:interval-anywhere',
  'lib/swarm-board/views/list/CardVerdict.svelte:fetch-in-component',
  'lib/terminal-search/PromptRail.svelte:own-tooltip',
  'lib/terminal-search/search-controller.svelte.ts:interval-anywhere',
  'lib/timers/TimerBadge.svelte:interval-anywhere',
  'lib/user-guide/GuideShot.svelte:own-tooltip',
  'opscenter/layout-editor/LayoutEditorHost.svelte:interval-anywhere',
  'opscenter/layouts/page.svelte.ts:interval-anywhere',
  'popout/popout.ts:interval-anywhere',
  'lib/widgets-page/PlaceMenu.svelte:menu-frame',
];

const KNOWN_CEILING = 46;

function sourcesOf(dir: string, base = ''): HostSource[] {
  return fs.readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const full = path.join(dir, entry.name);
    const rel = base ? `${base}/${entry.name}` : entry.name;
    if (entry.isDirectory()) return ['fixtures', '__goldens__', 'node_modules'].includes(entry.name) ? [] : sourcesOf(full, rel);
    if (!/\.(svelte|ts)$/.test(entry.name) || /\.(test|spec)\./.test(entry.name)) return [];
    return [{ path: rel, text: fs.readFileSync(full, 'utf8') }];
  });
}

const keyOf = (f: HostFinding): string => `${f.path}:${f.rule}`;

describe('wrappers are used, never copied', () => {
  const sources = sourcesOf(SRC);
  const found = scanWrappers(sources).map(keyOf);

  it('looked at the tree (a scan of nothing is not a pass)', () => {
    expect(sources.length).toBeGreaterThan(200);
    expect(sources.some((one) => one.path === 'opscenter/lib/frozen-clock.svelte.ts'), 'the shared clock is where the rule says').toBe(true);
  });

  it('has no copy outside KNOWN', () => {
    expect(found.filter((one) => !KNOWN.includes(one)), 'use the wrapper (CascadeMenu, the one tooltip, frozen-clock, the zone select, a store); never add to KNOWN').toEqual([]);
  });

  it('keeps every KNOWN row true (fixed code leaves the list) and only shrinks', () => {
    expect(KNOWN.filter((one) => !found.includes(one))).toEqual([]);
    expect(KNOWN.length).toBe(KNOWN_CEILING);
  });

  it('goes red on one planted copy per rule, and not on the owners, a selector or a comment', () => {
    const planted = scanWrappers([
      { path: 'lib/x/M.svelte', text: '<ul role="menu"><li role="menuitem">a</li></ul>' },
      { path: 'lib/x/Sel.svelte', text: "<script>el.querySelector('[role=\"menu\"]');</script><li role=\"menuitem\">a</li>" },
      { path: 'opscenter/ui/CascadeMenu.svelte', text: '<div role="menu"></div>' },
      { path: 'lib/x/Tip.svelte', text: '<span role="tooltip">t</span>' },
      { path: 'lib/x/Tip2.svelte', text: '<span class="x-tooltip">t</span>' },
      { path: 'lib/tooltip/tooltip.ts', text: "node.setAttribute('role', 'tooltip'); const c = 'class=\"oc-tooltip\"';" },
      { path: 'lib/x/Tick.ts', text: 'const id = setInterval(f, 1000);' },
      { path: 'opscenter/lib/frozen-clock.svelte.ts', text: 'setInterval(tick, 1000);' },
      { path: 'lib/x/Press.ts', text: "void pressRail('x'); openFlyout('y');" },
      { path: 'lib/zone-shell/left-rail-zone.svelte.ts', text: 'select: (key) => void pressRail(key),' },
      { path: 'lib/x/C.svelte', text: "<script>const r = await authFetch('/api/x');</script>" },
      { path: 'lib/x/store.ts', text: "const r = await authFetch('/api/x');" },
      { path: 'lib/x/L.svelte', text: '<StatusLed status={row.activity_status} unread={row.unread === true} size="9px" />' },
      { path: 'lib/x/L2.svelte', text: '<StatusLed\n  status={s}\n  {transport}\n/>' },
      { path: 'lib/x/L3.ts', text: 'const html = ledHtmlForStatus(row.status, signals);' },
      { path: 'lib/x/Glyph.svelte', text: '<StatusLed status="asleep" size="9px" /><StatusLed status={LED[k]} unread={false} startupGate={null} transport={null} /> <StatusLed status="working" />' },
      { path: 'lib/sessions/SessionFace.svelte', text: '<StatusLed status={a} unread={b} transport={c} />' },
      { path: 'lib/x/D.svelte', text: "<script>const r = store.fetch(1); // fetch('/x')\n</script><!-- <ul role=\"menu\"> -->" },
    ]).map(keyOf);
    expect(planted).toEqual([
      'lib/x/C.svelte:fetch-in-component',
      'lib/x/L.svelte:led-signals',
      'lib/x/L2.svelte:led-signals',
      'lib/x/L3.ts:led-signals',
      'lib/x/M.svelte:menu-frame',
      'lib/x/Press.ts:flyout-press',
      'lib/x/Tick.ts:interval-anywhere',
      'lib/x/Tip.svelte:own-tooltip',
      'lib/x/Tip2.svelte:own-tooltip',
    ]);
  });

  it('names every rule the planted control covers (a new rule needs its own plant)', () => {
    expect(WRAPPER_RULES.map((rule) => rule.name).sort()).toEqual(['fetch-in-component', 'flyout-press', 'interval-anywhere', 'led-signals', 'menu-frame', 'own-tooltip']);
  });
});
