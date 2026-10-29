import './lab-events';
import { params, fixtureKind, serveFixture, scenarioWanted, scenarioText } from './boot';
import '../app.css';
import '../opscenter/app.css';
import { mountPanel, unmountPanel } from '../lib/mount';
import Harness from './Harness.svelte';
import FitProbe from './FitProbe.svelte';
import DefectProbe from './DefectProbe.svelte';
import { harnessWidget, harnessWidgets } from './catalog';
import { registerDrafts } from './draft-entry';
import { fitCheck, unavailableFindings } from './fit-probe';
import { layoutDefects, type DefectReport } from './layout-defects';
import { menuConformance, type MenuDrawFinding } from './menu-conformance';
import { harnessState } from './state';
import { runIdleCheck, startIdleTracking } from './idle-run';
import { boxOverride } from './box-override';
import { openWidgetMenu } from './open-menu';
import { overlayScenario, parseScenario, tableToJson, unusedScenarioReads } from './scenario';
import { fixtureFor, hasFixture } from '../opscenter/widgets/fixtures';
import type { RouteTable } from '../opscenter/widgets/fixtures/types';
import { AMBIENT_ROUTES } from '../opscenter/widgets/fixtures/common';
import { SHELL_AMBIENT_ROUTES } from '../opscenter/widgets/fixtures/app-world';
import { initAuth, startActivity } from '../opscenter/api';
import { startClock } from '../opscenter/lib/frozen-clock.svelte';
import { pinGridViewport, watchViewport } from '../opscenter/engine/viewport.svelte';
import { refreshAnalytics } from '../opscenter/cells/analytics/state.svelte';
import { bindSessionFor } from './bound-session';
import { installTerminalStandIn } from './terminal-stand-in';
import { THEMES } from './themes';
import { CORE_ID, setMenuPreviewOnly } from '../lib/widget-menu/model';
import { installRemoteMenus } from './remote-menu';
import { paintTheme } from './paint-theme';
import type { FitZone } from '../opscenter/widgets/types';
import { withListing } from './listing-feed';
import { bootListingPush } from '../lib/listing-push/boot';
import { drawSidebar, sidebarClip } from './sidebar/draw-sidebar';
import { viewFromQuery, type SidebarView } from './sidebar/sidebar-state';
import { sidebarTable } from '../opscenter/widgets/fixtures/sidebar-world';
import { applyHarnessHostOptions } from './host-options';

applyHarnessHostOptions();

registerDrafts();
startIdleTracking(params.get('idle') === '1');

function railDock(): 'side' | 'bottom' | null {
  const dock = params.get('dock');
  return dock === 'side' || dock === 'bottom' ? dock : null;
}

const SIDEBAR_SHELL = params.get('shell') === 'sidebar';

const CONTAINER = 'widget-harness';

const QUIET_MS = 600;

const SETTLE_CAP_MS = 8000;

function settled(root: Element): Promise<void> {
  return new Promise((resolve) => {
    const started = performance.now();
    let last = performance.now();
    let requests = harnessState.requests;
    const observer = new MutationObserver(() => {
      last = performance.now();
    });
    observer.observe(root, { subtree: true, childList: true, attributes: true, characterData: true });
    const tick = (): void => {
      if (harnessState.requests !== requests) {
        requests = harnessState.requests;
        last = performance.now();
      }
      const now = performance.now();
      if (now - last >= QUIET_MS || now - started >= SETTLE_CAP_MS) {
        observer.disconnect();
        resolve();
        return;
      }
      setTimeout(tick, 100);
    };
    setTimeout(tick, 100);
  });
}

async function animationsDone(): Promise<void> {
  const running = document.getAnimations().filter((one) => one.playState === 'running' && one.effect?.getTiming().iterations !== Infinity);
  await Promise.race([Promise.all(running.map((one) => one.finished.catch(() => undefined))), new Promise((r) => setTimeout(r, 3000))]);
}

interface ShowRequest {
  zone: FitZone;
  size: string;
  theme: string;
  view?: SidebarView;
}

interface ShowResult {
  error: string;
  findings: (ReturnType<typeof fitCheck>[number] | MenuDrawFinding)[];
  misses: string[];
  text: string;
}

function readableText(cell: Element | null): string {
  if (!cell) return '';
  const parts = [(cell as HTMLElement).innerText ?? ''];
  for (const el of cell.querySelectorAll('input, textarea, [placeholder], [title], [aria-label]')) {
    for (const attr of ['placeholder', 'title', 'aria-label']) parts.push(el.getAttribute(attr) ?? '');
    if (el instanceof HTMLInputElement || el instanceof HTMLTextAreaElement) parts.push(el.value);
  }
  return parts.filter(Boolean).join('\n');
}

const widgetKey = params.get('widget') ?? '';

const PROBES: Readonly<Record<string, { component: unknown; props: Record<string, unknown> }>> = {
  'harness.fit-probe': { component: FitProbe, props: {} },
  'harness.defect-probe': { component: DefectProbe, props: {} },
  'harness.defect-probe-blank': { component: DefectProbe, props: { blank: true } },
};

function defects(): DefectReport | null {
  const cell = document.querySelector('[data-harness-cell]');
  return cell ? layoutDefects(cell) : null;
}

async function show(request: ShowRequest): Promise<ShowResult> {
  harnessState.ready = false;
  const probe = PROBES[widgetKey];
  if (probe) {
    unmountPanel(CONTAINER);
    await paintTheme(request.theme);
    mountPanel(CONTAINER, probe.component as never, probe.props);
    await document.fonts.ready;
    const drawnProbe = document.querySelector('[data-harness-cell]');
    harnessState.ready = true;
    return { error: '', findings: drawnProbe ? fitCheck(drawnProbe) : [], misses: [], text: readableText(drawnProbe) };
  }
  const widget = harnessWidget(widgetKey);
  if (SIDEBAR_SHELL && widget) return showSidebar(widget, request);
  const published = (request.zone === 'popout' ? (widget?.sizes.popout ?? widget?.sizes.home) : widget?.sizes[request.zone])?.find((one) => one.name === request.size);
  const override = boxOverride(params);
  const size = published && override ? { ...published, ...override } : published;
  if (!widget || !size) {
    const error = !widget ? `no widget ${widgetKey}` : `${widgetKey} declares no zone ${request.zone} or size ${request.size}`;
    harnessState.ready = true;
    return { error, findings: [], misses: [], text: '' };
  }
  unmountPanel(CONTAINER);
  await paintTheme(request.theme);
  mountPanel(CONTAINER, Harness as never, { widget, zone: request.zone, size, dock: railDock() });
  const root = document.getElementById(CONTAINER)!;
  await document.fonts.ready;
  await settled(root);
  await animationsDone();
  await new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));
  const cell = document.querySelector('[data-harness-cell]');
  const fit = cell ? [...fitCheck(cell), ...unavailableFindings(cell, size.declared === true)] : [];
  const menus = cell ? menuConformance(cell, widget.manifest) : [];
  harnessState.ready = true;
  return { error: '', findings: [...fit, ...menus], text: readableText(cell), misses: [...new Set(harnessState.misses)].filter((miss) => !AMBIENT_ROUTES.has(miss)) };
}

/* the real left sidebar */
async function showSidebar(widget: NonNullable<ReturnType<typeof harnessWidget>>, request: ShowRequest): Promise<ShowResult> {
  harnessState.ready = false;
  await paintTheme(request.theme);
  await drawSidebar(request.view ?? viewFromQuery(params));
  const root = document.body;
  await document.fonts.ready;
  await settled(root);
  await animationsDone();
  await new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));
  const area = document.getElementById('session-sidebar-ledger');
  area?.setAttribute('data-harness-cell', '');
  const cell = area && area.getBoundingClientRect().height > 0 ? area : null;
  const shown: ShowResult = { error: '', findings: cell ? fitCheck(cell) : [], text: readableText(cell), misses: [...new Set(harnessState.misses)].filter((miss) => !AMBIENT_ROUTES.has(miss) && !SHELL_AMBIENT_ROUTES.has(miss)) };
  const state = harnessState as typeof harnessState & Record<string, unknown>;
  state['result'] = { ...(state['result'] as object | undefined), ...shown, hasFixture: hasFixture(widget.key), clip: sidebarClip(), plate: false, unusedScenarioRoutes: [], fixtureJson: (state['result'] as { fixtureJson?: string } | undefined)?.fixtureJson ?? '', menu: { asked: false, open: false, reason: '' } };
  harnessState.ready = true;
  return shown;
}

interface DrawReport extends ShowResult {
  hasFixture: boolean;
  fixtureJson: string;
  plate: boolean;
  unusedScenarioRoutes: string[];
  menu: { asked: boolean; open: boolean; reason: string };
  clip?: { w: number; h: number } | null;
}

async function chooseTable(): Promise<{ table: RouteTable; scenario: RouteTable | null; error: string }> {
  const own = fixtureFor(widgetKey, fixtureKind);
  const base = SIDEBAR_SHELL ? sidebarTable(own, fixtureKind, harnessWidget(widgetKey)) : own;
  if (!scenarioWanted) return { table: base, scenario: null, error: '' };
  const parsed = parseScenario(await scenarioText);
  if (!parsed.ok) return { table: base, scenario: null, error: `scenario: ${parsed.error}` };
  return { table: overlayScenario(base, parsed.table), scenario: parsed.table, error: '' };
}

async function boot(): Promise<void> {
  const state = harnessState as typeof harnessState & Record<string, unknown>;
  state['show'] = show;
  state['defects'] = defects;
  state['idle'] = runIdleCheck;
  if (params.get('list') === '1') {
    state['catalog'] = harnessWidgets().map((one) => ({ ...one, fixture: hasFixture(one.key) }));
    state['themes'] = THEMES;
    serveFixture({});
    harnessState.ready = true;
    return;
  }
  const chosen = await chooseTable();
  if (chosen.error) {
    harnessState.error = chosen.error;
    harnessState.ready = true;
    return;
  }
  serveFixture(withListing(chosen.table));
  bootListingPush();
  bindSessionFor(widgetKey);
  installTerminalStandIn(widgetKey);
  const size = params.get('size') ?? 'm';
  initAuth();
  startClock();
  if (params.get('lab') === '1' && size !== 'phone') pinGridViewport();
  else watchViewport();
  if (params.get('lab') === '1') {
    if (!SIDEBAR_SHELL) installRemoteMenus();
    setMenuPreviewOnly([CORE_ID.popOut, CORE_ID.focusMain, CORE_ID.closeWidget, CORE_ID.removeWidget, CORE_ID.editLayout, CORE_ID.doneEditing, CORE_ID.moveToDrawer, CORE_ID.moveToBar]);
  }
  startActivity();
  if (widgetKey.startsWith('core.analytics:')) await refreshAnalytics();
  const result = await show({
    zone: (params.get('zone') ?? 'home') as FitZone,
    size,
    theme: params.get('theme') ?? THEMES[0]!,
  });
  const asked = params.get('state') === 'menu';
  if (asked) harnessState.ready = false;
  const opening = asked && !result.error ? await openWidgetMenu(document.querySelector('[data-harness-cell]')) : { ok: false, reason: result.error };
  const report: DrawReport = {
    ...result,
    hasFixture: hasFixture(widgetKey),
    fixtureJson: tableToJson(chosen.table),
    plate: document.querySelector('[data-harness-cell] [data-widget-unavailable]') !== null,
    unusedScenarioRoutes: chosen.scenario ? unusedScenarioReads(chosen.scenario, harnessState.asked) : [],
    menu: { asked, open: opening.ok, reason: asked ? opening.reason : '' },
    ...(SIDEBAR_SHELL ? { clip: sidebarClip() } : {}),
  };
  state['result'] = report;
  harnessState.error = result.error || (asked && !opening.ok ? opening.reason : '');
  harnessState.ready = true;
}

boot().catch((error: unknown) => {
  harnessState.error = error instanceof Error ? error.message : String(error);
  harnessState.ready = true;
});
