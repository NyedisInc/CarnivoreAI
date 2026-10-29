import { faceFacts } from '../../../lib/sessions/agent-marks';
import { tick } from 'svelte';
import { terminalLayout } from '../../engine/layout.svelte';
import { activeTabFor, openTab, removeTab, replaceTab, selectTab, tabsFor } from '../../engine/tab-groups.svelte';
import { browserRunningHost, type RunningHost } from '../../../lib/launchpad/running-host';
import { ACTION_CLOSE, runRowAction } from '../../../lib/launchpad/running-actions';
import type { RunningSessionRow } from '../../../lib/sessions/types';
import { createAsTab } from '../../engine/tab-landing';
import { focusTab } from '../../engine/tab-drag';
import { buildTabMenu } from '../../shell/tab-menu';
import type { TabItem } from '../../shell/TabStrip.svelte';
import { t } from '../../../lib/i18n/index.svelte';
import type { ProjectResponse, SessionInfo } from '../../api/types';
import { inputFocus } from '../../lib/input-focus.svelte';
import { PRIMARY_SLOT } from '../../engine/model';
import { PRIMARY_BIND_EVENT } from '../../engine/primary-bind';
import {
  openHome, openSession as navigateTo, primarySessionId, primaryTmuxName, startNewSession, startNewSessionInProject,
} from '../../api/host';
import { sessions, asleep, recent, projects, wakeOrPick, openBlueprints } from '../../api';
import { openModal } from '../../../lib/modal';
import LaunchModal from '../../../lib/blueprints/LaunchModal.svelte';
import { listBlueprints } from '../../../lib/blueprints/api';
import type { Blueprint } from '../../../lib/blueprints/types';
import { asleepRows, isAsleepRow } from '../running-sessions/asleep';
import { rowFor, sessionIdOf } from '../terminal-viewer/meta';
import { takenSlots } from '../../engine/components-actions';
import { isTabSlot } from '../../engine/tabs';
import { pageIdOfTab, pageTabId } from '../../engine/page-tabs';
import { isNonSessionTab, isWidgetTab, widgetIdOfTab, widgetTabId } from '../../engine/widget-tabs';
import { pageMenuRows, pageTabItem } from './page-tab-item';
import { widgetMenuNodes, widgetTabItem } from './widget-tab-item';
import { moveWidgetTabOptions } from './widget-tab-source.svelte';
import { browsers, createBrowser } from '../../../lib/browser/api.svelte';
import { openPages } from '../../../lib/browser/pages.svelte';
import { openFiles } from '../../../lib/open-files/api.svelte';
import { rowIdOfSlot, slotForSession } from '../../engine/slot-identity';
import { transportFor } from '../terminal-live/connection.svelte';
import { layoutActive } from '../../layouts/mode.svelte';
import { anchorGone, removeAnchor } from '../../layouts/page.svelte';
import type { TabSource } from '../../layouts/phone.svelte';
import { openBrowserItemMenu, openRowMenu, uuidOfTmuxName } from '../terminal-live/row-menu';
import { pageTabState } from './page-tab-state.svelte';
import type { MenuNode } from '../../../lib/drawer-tabs/add-component-menu';

function displayName(label: string | null, tmuxName: string | null): string | null {
  const resolver = (globalThis as {
    SessionLabel?: { resolve(row: { label: string | null; name: string | null }): string | null };
  }).SessionLabel;
  return resolver ? resolver.resolve({ label, name: tmuxName }) : (label ?? '').trim() || null;
}

export const PRIMARY_SESSION_GONE_EVENT = 'cloude:primary-session-gone';

interface ThemeRegistry {
  getSessionManifest?(context: { pinnedTheme: string | null }): { cssVars?: Record<string, string> } | null;
  onXtermThemeChange?(callback: () => void): () => void;
}

function themes(): ThemeRegistry | undefined {
  return (globalThis as { Themes?: ThemeRegistry }).Themes;
}

export function createTabController(instance: () => string, focusPane: (tab: string) => void, source?: TabSource) {
  const tabs = $derived(source ? source.tabs() : tabsFor(terminalLayout, instance()));
  const active = $derived(source ? source.active() : activeTabFor(terminalLayout, instance()));

  let boundSession = $state(primarySessionId());
  $effect(() => {
    boundSession = primarySessionId();
    const onBind = (event: Event): void => {
      const id = (event as CustomEvent<{ sessionId?: string }>).detail?.sessionId;
      if (id) boundSession = id;
    };
    globalThis.addEventListener(PRIMARY_BIND_EVENT, onBind);
    return () => globalThis.removeEventListener(PRIMARY_BIND_EVENT, onBind);
  });

  $effect(() => {
    if (instance() !== PRIMARY_SLOT) return;
    const onGone = (): void => {
      if (layoutActive()) void anchorGone();
      else close(PRIMARY_SLOT);
    };
    globalThis.addEventListener(PRIMARY_SESSION_GONE_EVENT, onGone);
    return () => globalThis.removeEventListener(PRIMARY_SESSION_GONE_EVENT, onGone);
  });

  let themeRevision = $state(0);
  $effect(() => themes()?.onXtermThemeChange?.(() => (themeRevision += 1)));

  function accentFor(pinnedTheme: string | null): string | null {
    void themeRevision;
    return themes()?.getSessionManifest?.({ pinnedTheme })?.cssVars?.['--color-accent'] ?? null;
  }

  function sessionOf(tab: string): string {
    if (tab !== PRIMARY_SLOT) return sessionIdOf(tab, sessions.data);
    if (rowFor(sessions.data, boundSession)) return boundSession;
    const tmux = primaryTmuxName();
    const same = tmux ? sessions.data?.find((row) => row.tmux_session === tmux) : null;
    return same?.session?.id ?? boundSession;
  }

  function sleepingFor(rowId: number | null) {
    return rowId === null ? null : (asleep.data ?? []).find((rec) => rec.id === rowId && rec.asleep !== false) ?? null;
  }

  const items = $derived<TabItem[]>(
    tabs.map((id) => {
      const pageId = pageIdOfTab(id);
      if (pageId !== null) return pageTabItem(id, pageId);
      const widgetId = widgetIdOfTab(id);
      if (widgetId !== null) return widgetTabItem(id, widgetId);
      const sessionId = sessionOf(id);
      const row = rowFor(sessions.data, sessionId);
      const rowId = row ? null : rowIdOfSlot(id);
      const sleeping = sleepingFor(rowId);
      const stored = row || sleeping || rowId === null
        ? null
        : (recent.data?.sessions ?? []).find((rec) => rec.id === rowId) ?? null;
      return {
        id,
        name: displayName(
          row?.label ?? sleeping?.title ?? stored?.title ?? null,
          row?.tmux_session ?? sleeping?.tmux_name ?? stored?.tmux_name ?? (id === PRIMARY_SLOT ? primaryTmuxName() || null : null),
        ) || sessionId,
        family: row?.agent_family ?? sleeping?.agent_family ?? null,
        tint: accentFor(row?.pinned_theme ?? sleeping?.pinned_theme ?? null),
        face: row
          ? faceFacts(row, { transport: transportFor(sessionId) })
          : faceFacts({ agent_family: sleeping?.agent_family ?? null, unread: sleeping?.unread }, { lifecycle: sleeping ? 'asleep' : undefined, transport: transportFor(sessionId) }),
        workflow: row?.workflow_active === true,
        agent: row ? (row as unknown as Record<string, unknown>) : null,
      };
    }),
  );

  const activePin = $derived.by(() => {
    if (isNonSessionTab(active)) return null;
    const row = rowFor(sessions.data, sessionOf(active));
    return row ? row.pinned_theme ?? null : sleepingFor(rowIdOfSlot(active))?.pinned_theme ?? null;
  });

  function select(tab: string): void {
    if (tab === active) return;
    if (!isNonSessionTab(tab)) inputFocus.claim(tab);
    if (source) source.select(tab);
    else selectTab(terminalLayout, instance(), tab);
    void tick().then(() => focusPane(tab));
  }

  function close(tab: string): void {
    if (tab === PRIMARY_SLOT && layoutActive()) {
      void removeAnchor();
      return;
    }
    const at = tabs.indexOf(tab);
    const next = tabs[at + 1] ?? tabs[at - 1];
    if (tab !== PRIMARY_SLOT) {
      if (tab === active && next && !isNonSessionTab(next)) inputFocus.claim(next);
      removeTab(terminalLayout, tab);
      if (isWidgetTab(tab)) moveWidgetTabOptions(tab, null);
      return;
    }
    if (!next) {
      openHome();
      return;
    }
    const id = sessionOf(next);
    navigateTo(id, rowFor(sessions.data, id)?.tmux_session ?? null);
  }

  async function kill(tab: string): Promise<void> {
    if (isNonSessionTab(tab)) {
      close(tab);
      return;
    }
    const sessionId = sessionOf(tab);
    const row = rowFor(sessions.data, sessionId);
    const tmuxName = row?.tmux_session ?? (tab === PRIMARY_SLOT ? primaryTmuxName() : '');
    if (!tmuxName) return;
    const real = browserRunningHost();
    let killed = false;
    const host: RunningHost = {
      ...real,
      async destroySession(id: string): Promise<unknown> {
        const result = await real.destroySession(id);
        killed = true;
        return result;
      },
      async destroyExternalSession(name: string): Promise<unknown> {
        const result = await real.destroyExternalSession(name);
        killed = true;
        return result;
      },
    };
    const target = { name: tmuxName, label: row?.label ?? null, session_id: sessionId } as RunningSessionRow;
    await runRowAction(target, ACTION_CLOSE, host, t);
    void sessions.refresh();
    if (killed) close(tab);
  }

  let newAnchor = $state<HTMLElement | null>(null);

  let blueprintRows = $state<Blueprint[]>([]);
  $effect(() => {
    if (!newAnchor) return;
    void listBlueprints()
      .then((list) => {
        if (list.status === 'ok') blueprintRows = list.blueprints;
      })
      .catch(() => {});
  });

  function launchBlueprintFromMenu(blueprint: Blueprint): void {
    closeMenu();
    void openModal(LaunchModal, { uuid: blueprint.blueprint_uuid, name: blueprint.name });
  }

  function openSession(sessionId: string): void {
    const tab = sessionId === boundSession ? PRIMARY_SLOT : slotForSession(sessionId, sessions.data);
    inputFocus.claim(tab);
    openTab(terminalLayout, instance(), tab);
    void tick().then(() => focusTab(tab));
  }

  function openPage(browserId: string): void {
    newAnchor = null;
    openTab(terminalLayout, instance(), pageTabId(browserId));
  }

  function swapWidgetTab(tab: string, to: string): void {
    if (replaceTab(terminalLayout, tab, to)) moveWidgetTabOptions(tab, to);
  }

  function openWidget(widgetId: string): void {
    newAnchor = null;
    openTab(terminalLayout, instance(), widgetTabId(widgetId));
  }

  async function createBrowserTab(): Promise<void> {
    newAnchor = null;
    const layoutKey = terminalLayout.session;
    try {
      const made = await createBrowser();
      if (terminalLayout.session === layoutKey) openPage(made.id);
    } catch (err) {
      console.error('tab menu: browser create refused', err);
      terminalLayout.announce(t('browser.create_failed', { detail: err instanceof Error ? err.message : String(err) }));
    }
  }

  const pagesAllowed = $derived(!source);

  function landCreated(id: string): void {
    const layoutKey = terminalLayout.session;
    void Promise.resolve(sessions.refresh(true)).then(() => {
      if (terminalLayout.session === layoutKey) openSession(id);
    });
  }

  function create(kind: 'agent' | 'terminal'): void {
    newAnchor = null;
    void createAsTab(() => startNewSession(kind), landCreated);
  }

  function createInProject(project: ProjectResponse): void {
    newAnchor = null;
    void createAsTab(() => startNewSessionInProject(project as unknown as Record<string, unknown>), landCreated);
  }

  function closeMenu(): void {
    const anchor = newAnchor;
    newAnchor = null;
    anchor?.focus();
  }

  async function wakeAsleepRow(row: SessionInfo): Promise<void> {
    if (!isAsleepRow(row)) return;
    await wakeOrPick(row.session_uuid, row.tmux_session ?? '', displayName(row.label ?? null, row.tmux_session ?? null) || row.session.id);
    await Promise.all([asleep.refresh(), sessions.refresh()]);
  }

  /* running sessions */
  const menuRows = $derived.by(() => {
    const live = (sessions.data ?? []) as SessionInfo[];
    const liveNames = new Set(live.map((row) => row.tmux_session).filter((n): n is string => !!n));
    return [...live, ...asleepRows(asleep.data ?? [], liveNames)];
  });

  const layoutTabs = $derived(source ? source.tabs() : takenSlots(terminalLayout).filter(isTabSlot).flatMap((slot) => tabsFor(terminalLayout, slot)));

  const layoutSessionIds = $derived(
    layoutTabs
      .filter((tab) => !isNonSessionTab(tab))
      .map(sessionOf),
  );

  const menu = $derived(
    newAnchor
      ? buildTabMenu({
          rows: menuRows,
          name: (row) => displayName(row.label ?? null, row.tmux_session ?? null) || row.session.id,
          open: (id) => {
            closeMenu();
            openSession(id);
          },
          wake: (row) => {
            closeMenu();
            void wakeAsleepRow(row);
          },
          newAgent: () => create('agent'),
          newAgentInProject: (project) => createInProject(project),
          newTerminal: () => create('terminal'),
          openBlueprints: () => {
            closeMenu();
            openBlueprints();
          },
          blueprints: blueprintRows,
          launchBlueprint: launchBlueprintFromMenu,
          openSessionIds: new Set(tabs.filter((tab) => !isNonSessionTab(tab)).map(sessionOf)),
          pages: pagesAllowed
            ? pageMenuRows(openPages.data ?? [], openFiles.data ?? [], browsers.data ?? [], new Set(tabs))
            : null,
          openPage,
          newBrowser: () => void createBrowserTab(),
          widgets: pagesAllowed ? widgetMenuNodes(new Set(layoutTabs), openWidget) : null,
          layoutSessionIds,
          projects: projects.data ?? [],
        })
      : [],
  );

  let tabMenuAnchor = $state<HTMLElement | null>(null);
  let tabMenuTab = $state<string | null>(null);

  const tabMenuNodes = $derived<MenuNode[]>(
    tabMenuTab === null ? [] : [{ id: 'close', label: t('opscenter.tabs.menu_close'), run: () => { const tab = tabMenuTab!; tabMenuAnchor = null; tabMenuTab = null; close(tab); } }],
  );

  function closeTabMenu(): void {
    tabMenuAnchor = null;
    tabMenuTab = null;
  }

  /* keep awake */
  function openTabMenu(tab: string, anchor: HTMLElement, point: { x: number; y: number } | null): boolean {
    const where = point ? { point } : {};
    const pageId = pageIdOfTab(tab);
    if (pageId !== null) {
      const { kind, title } = pageTabState(pageId);
      if (kind === 'file' || kind === 'page' || kind === 'browser') return openBrowserItemMenu(kind, pageId, title, anchor, where);
      return openSmallMenu(tab, anchor);
    }
    const row = rowFor(sessions.data, sessionOf(tab));
    if (row?.tmux_session) return openRowMenu(row, uuidOfTmuxName(row.tmux_session), anchor, where);
    const sleeping = sleepingFor(rowIdOfSlot(tab));
    const asleepRow = sleeping ? asleepRows([sleeping], new Set())[0] : undefined;
    if (asleepRow) return openRowMenu(asleepRow, asleepRow.session_uuid, anchor, where);
    return openSmallMenu(tab, anchor);
  }

  function openSmallMenu(tab: string, anchor: HTMLElement): boolean {
    tabMenuTab = tab;
    tabMenuAnchor = anchor;
    return true;
  }

  return {
    get tabs() {
      return tabs;
    },
    get active() {
      return active;
    },
    get items() {
      return items;
    },
    get activePin() {
      return activePin;
    },
    get menu() {
      return menu;
    },
    get newAnchor() {
      return newAnchor;
    },
    set newAnchor(anchor: HTMLElement | null) {
      newAnchor = anchor;
    },
    sessionOf,
    select,
    close,
    kill,
    openTabMenu,
    swapWidgetTab,
    get tabMenuAnchor() {
      return tabMenuAnchor;
    },
    get tabMenuNodes() {
      return tabMenuNodes;
    },
    closeTabMenu,
  };
}
