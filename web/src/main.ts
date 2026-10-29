/* <script */
import './cplugs/host/early-kinds';
import './app.css';
import './opscenter/app.css';
import './lib/first-run/boot';
import './lib/manager-frame/manager-frame.css';
import './lib/manager-frame/manager-card.css';
import './lib/menu-page/menu-page.css';
import './lib/item-settings/settings-form.css';
import './lib/icon-picker/icon-picker.css';
import './lib/tooltip/tooltip.css';
import { mount, unmount } from 'svelte';
import StatusLed from './lib/StatusLed.svelte';
import * as led from './lib/led';
import { ledHtmlForStatus, labelFor, labelWithSource, normalizeStatus } from './lib/status-dot';
import type { StatusSignals } from './lib/status-dot';
import { ensurePanel, mountPanel } from './lib/mount';
import { openForkPicker } from './lib/crosstalk/fork-picker';
import { closeCatalogScreen, openCatalogScreen, wireCatalogDeepLink } from './lib/catalog/screen-host';
import { closeWarezScreen } from './lib/catalog/warez-host';
import { closeLedgerScreen, openLedgerScreen, wireLedgerDeepLink } from './lib/ledger/screen-host';
import { mountHelpReleases, unmountHelpReleases, mountHelpFeatures, unmountHelpFeatures } from './lib/help/host';
import { closeThemesScreen, openThemesScreen, wireThemesDeepLink } from './lib/themes-page/screen-host';
import { browserBridge, closeBrowserScreen, wireBrowserDeepLink } from './lib/browser/screen-host';
import { layoutsBridge } from './lib/layouts-bridge/bridge';
import { addToMenuBridge } from './lib/add-to-menu/host';
import { rowMenuBridge } from './lib/item-menu/row-bridge';
import { installRowMenuOpener } from './lib/item-menu/row-open';
import { claimOpenMenu } from './lib/drawer-tabs/open-menu';
import { placeMenu } from './lib/drawer-tabs/add-component-menu';
import { sendToBridge } from './lib/send-to/host';
import { moveToFolderBridge } from './lib/session-move/host';
import { sidebarShell } from './lib/sidebar-shell/shell.svelte';
import { showPath } from './lib/sidebar-shell/show-path';
import { bootDrawer } from './lib/drawer/boot';
import { publishTerminalProvider } from './lib/terminal-provider/publish';
import { mountDrawerHeader } from './lib/drawer/header-mount';
import { bootListingPush } from './lib/listing-push/boot';
import { bootResourcePush } from './lib/resource-push/boot';
import { startOutbox } from './lib/outbox/outbox';
import { bootNativeShell } from './lib/native-shell/shell';
import { installNotifyScreen } from './lib/notifications/screen-filter';
import { installNotifyMute } from './lib/notifications/mute/mute-control';
import { startPresenceBeacon } from './lib/notifications/presence';
import { closeBlueprintsScreen, openBlueprintsScreen, wireBlueprintsDeepLink } from './lib/blueprints/screen-host';
import { openBlueprintPicker } from './lib/blueprints/blueprint-picker';
import { askLeaderConfirm } from './lib/leader-confirm/confirm';
import { closePluginsScreen, openPluginsScreen, wirePluginsDeepLink } from './lib/plugins-page/screen-host';
import { closeSkillsManagerScreen } from './lib/skills-page/screen-host';
import {
    closeChangelogScreen, closeDocsScreen,
    openDocsScreen, wireInfoPageDeepLinks,
} from './lib/info-pages/screen-host';
import { closeLogsScreen, openLogsScreen, wireLogsDeepLink } from './lib/logs-page/screen-host';
import { closeWarroomScreen, wireWarroomDeepLink } from './lib/warroom/screen-host';
import { startWarroomSync } from './opscenter/engine/warroom-sync.svelte';
import { closeHuddleAgentScreen, wireHuddleAgentDeepLink } from './lib/huddle-agent/screen-host';
import './lib/plugins-page/plugin-pages';
import { closeHuddleSwarmScreen, wireHuddleSwarmDeepLink } from './lib/huddle-swarm/screen-host';
import { closeWidgetsScreen, openWidgetsScreen, wireWidgetsDeepLink } from './lib/widgets-page/screen-host';
import { mountLaunchChoice, openLaunchPicker } from './lib/launch-picker/open';
import { installSettingsShortcut } from './lib/settings-page/settings-shortcut';
import { closeSettingsScreen, openSettingsScreen, openSettingsSection, wireSettingsDeepLink } from './lib/settings-page/screen-host';
import { closeDashboardsScreen, wireDashboardsDeepLink } from './lib/dashboards/screen-host';
import { closeModsScreen, wireModsDeepLink } from './lib/mods/screen-host';
import { closeEliteScreen, wireEliteDeepLink } from './lib/elite/elite-host';
import { closeHostsScreen, openHostsScreen, wireHostsDeepLink } from './lib/pack-page/screen-host';
import { closeAutomationsScreen, openAutomationsScreen, wireAutomationsDeepLink } from './lib/automations/screen-host';
import { openScheduleThis } from './lib/automations/schedule-prefill';
import { closeAccountScreen, openAccountScreen, wireAccountDeepLink } from './lib/carnivore-account/account-host';
import {
    closeSessionsScreen,
    openSessionsScreen,
    wireSessionsDeepLinks,
} from './lib/sessions-page/screen-host';
import { blueprintsLegacyBridge } from './lib/blueprints/legacy-bridge';
import { autoSleepBridge, startAutoSleep } from './lib/auto-sleep/host';
import { startSessionDiedFrames } from './lib/session-died/session-died-toast';
import { startCrosstalkCards } from './lib/crosstalk/terminal-cards/start';
import { iconSvgString } from './opscenter/ui/icon-svg';
import { themeFavorites } from './lib/themes-page/favorites.svelte';
import { browserCreateHost, type CreateHost } from './lib/launchpad/create-host';
import { browserModals } from './lib/launchpad/modals';
import { createConsoleFlow, createProjectFlow } from './lib/launchpad/create-flow';
import {
    cloneFromGithubFlow,
    startNewClaudeProject as startNewClaudeProjectFlow,
    startSessionInExistingProject as startSessionInExistingProjectFlow,
} from './lib/launchpad/entry-flows';
import { openProjectFromFolderFlow } from './lib/launchpad/open-folder-flow';
import {
    archiveProjectFlow,
    editProjectFlow,
    unarchiveProjectFlow,
} from './lib/launchpad/project-actions';
import type { ProjectRow } from './lib/sessions/types';
import AttributionPrompt from './lib/launchpad/AttributionPrompt.svelte';
import RecentSessions from './lib/launchpad/RecentSessions.svelte';
import ProjectTree from './lib/launchpad/ProjectTree.svelte';
import RunningSessions from './lib/launchpad/RunningSessions.svelte';
import {
    archiveSessionRecord,
    browserHost as recentBrowserHost,
    forkSession,
    restartRecentSession,
} from './lib/launchpad/recent-actions';
import type { RestartOptions } from './lib/launchpad/recent';
import { sessionStore } from './lib/sessions/store.svelte';
import { workStampFor } from './lib/sessions/attribution';
import {
    derivedDisplayName,
    sessionDisplayLabel,
    type NameableRow,
} from './lib/sessions/session-label';
import type { RunningSessionRow } from './lib/sessions/types';
import { uiPrefs } from './lib/ui/prefs.svelte';
import './lib/plugins/builtin';
import './opscenter/layouts/publish';
import { sessionCardMenuItems, runSessionCardAction } from './lib/plugins/session-card-actions';
import { t, setLocale, currentLocale, i18n } from './lib/i18n/index.svelte';
import { summaryLabel } from './lib/session-summary-label';
import { mountHomeScreen, launchpadScreen, unmountHomeScreen } from './lib/launchpad/home-screen-host';
import { openSubagentList } from './lib/subagents/popup';
import { openAttachmentLightbox } from './lib/attachment-lightbox/open';
import { openTimerList } from './lib/timers/popup';
import { pauseAll as pauseHomePolls, restartAll as resumeHomePolls } from './opscenter/api';
import { refreshLaunchpadPanels } from './lib/launchpad/panels';
import { publishLaunchpadShim } from './lib/launchpad/shim';
import { browserNavHost } from './lib/launchpad/nav-host';
import {
    attachRunningSession as attachRunningSessionFlow,
    connectToExistingSession as connectToExistingSessionFlow,
    detachAndCreateNew as detachAndCreateNewFlow,
    detachAndOpenProject as detachAndOpenProjectFlow,
    explainRefusedProject,
    isResolvingDeepLink,
    openProjectByName as openProjectByNameFlow,
    returnToActiveSession as returnToActiveSessionFlow,
    selectProject as selectProjectFlow,
} from './lib/launchpad/navigation';
import { showError as showHomeError, updateStatus } from './lib/launchpad/status-report';
import {
    mountTerminalSearch,
    openTerminalSearch,
    terminalSearchIsOpen,
    toggleTerminalSearch,
    unmountTerminalSearch,
} from './lib/terminal-search/mount-search';
import { mountSpectateIfNeeded } from './spectate/mount';
import { mountDrawerTabs } from './lib/drawer-tabs/mount-drawer-tabs';
import { initMenuPageShell } from './lib/menu-page/menu-page-shell.svelte';
import './lib/launchpad/home-escape';
import './lib/launchpad/home-in-main.css';
import { initHomeInMain } from './lib/launchpad/home-in-main';
import { pageOfHash } from './lib/menu-page/menu-page-hash';
import MenuPageBar from './lib/menu-page/MenuPageBar.svelte';
import { mountLayoutEditor } from './opscenter/layout-editor/mount';
import { layoutEditorBridge } from './opscenter/layout-editor/editor.svelte';
import { mountFileDrawerGit, mountFileDrawerHeader, showFilesCell } from './lib/file-drawer/file-drawer';
import { openFromDrawer } from './lib/open-files/open-bridge';
import { guardUnload } from './lib/open-files/buffers.svelte';
import { watchOrphans } from './lib/open-files/orphans.svelte';
import { mountIconPicker, unmountIconPicker } from './lib/icon-picker/icon-picker-host';
import { installSharedTooltip } from './lib/tooltip/tooltip';
import VersionBanner from './lib/version-watch/VersionBanner.svelte';
import RelayConsentPopup from './lib/pack-machines/RelayConsentPopup.svelte';
import PackOpToast from './lib/pack-op-toast/PackOpToast.svelte';
import OverlayRoot from './lib/cplug-ui/OverlayRoot.svelte';
import { startVersionWatch } from './lib/version-watch/version-watch.svelte';
import { startPerfOverlay } from './lib/perf-overlay/boot';
import { rightDrawerApi } from './lib/right-drawer/api';
import { followBrowserSelect } from './lib/browser/select-push.svelte';
import { startActivityReport, startGoneReport } from './lib/ui-show/activity';
import { followUiShow } from './lib/ui-show/show-push.svelte';
import { followActiveTerminal } from './lib/right-drawer/files-follow.svelte';
import { claimSizeMaster, releaseSizeMaster, sizeMasters, thisTabId } from './opscenter/api/size-master.svelte';
import { installSignInModal } from './lib/carnivore-account/open-signin';
import { installWelcome } from './lib/carnivore-account/open-welcome';
import { installRefusalHandler } from './lib/carnivore-account/refusal';
import { masterAll, setMasterAll, startMasterAll } from './opscenter/api/master-all.svelte';
import {
    mountSessionNotes,
    toggleSessionNotes,
} from './lib/notes-header/mount-notes';
import { mountAppAlerts } from './lib/app-alerts/mount-alerts.svelte';
import { startApprovals } from './lib/approvals/approvals.svelte';
import { openApprovalFor, wireAskOpeners } from './lib/approvals/mount-approvals.svelte';
import { startMenuCommands } from './lib/desktop-menu/browser-actions';
import { runCplugCardAction, startCplugs } from './cplugs/host/readers';
import {
    clearTerminalStartupNotice,
    showTerminalStartupNotice,
} from './lib/terminal-notice/mount-notice';
import {
    clearTerminalSizeNotice,
    showTerminalSizeNotice,
} from './lib/terminal-notice/mount-size-notice';
import { mountTerminalFoot } from './lib/terminal-foot-bar/mount-terminal-foot';
import { closeTerminalEmpty, openTerminalEmpty } from './lib/terminal-empty/mount-empty';
import { mountSlashFavorites, setSlashFavorites } from './lib/slash-favorites/mount-slash-favorites';
import {
    closeTerminalComponents,
    mountTerminalGrid,
    openTerminalComponents,
    terminalComponentsOpen,
    unmountTerminalGrid,
} from './opscenter/terminal-surface-host';
import { mountTerminalPhoneTabs, unmountTerminalPhoneTabs } from './opscenter/phone-tabs-host';
import { hideSoloPanel, showSoloPanel } from './lib/solo/solo-host';
import { startArrangementSync } from './opscenter/engine/arrangement-sync.svelte';
import { startHomeSync } from './opscenter/engine/home-sync.svelte';
import { runLayoutMigration } from './opscenter/layouts/migrate';
import { beginDrawerTabDrag } from './opscenter/engine/tab-drag';
import { startContextLinks } from './lib/deepsearch/context-link.svelte';

installSharedTooltip();

const ATTRIBUTION_PROMPT_CONTAINER = 'attribution-prompt';

const RECENT_SESSIONS_CONTAINER = 'recent-sessions-list';

const PROJECT_TREE_CONTAINER = 'project-list';

const RUNNING_SESSIONS_CONTAINER = 'running-sessions-list';

const VERSION_BANNER_CONTAINER = 'version-banner-container';

const recentHost = recentBrowserHost(() =>
    sessionStore.refreshRecent(
        (includeArchived) => recentHost.fetchRecent(includeArchived),
        uiPrefs.archivedSessionsVisible,
        t,
    ),
);

function mountAttributionPrompt(): void {
    mountPanel(ATTRIBUTION_PROMPT_CONTAINER, AttributionPrompt, {});
}

function mountRecentSessions(): void {
    mountPanel(RECENT_SESSIONS_CONTAINER, RecentSessions, {});
}

/* version mismatch */
function mountVersionBanner(): void {
    startVersionWatch();
    mountPanel(VERSION_BANNER_CONTAINER, VersionBanner, {});
}

function mountProjectTree(): void {
    ensurePanel(PROJECT_TREE_CONTAINER, ProjectTree, {});
}

function mountRunningSessions(): void {
    ensurePanel(RUNNING_SESSIONS_CONTAINER, RunningSessions, {});
}

function displayNameForLegacy(tmuxName: string | null): string {
    return derivedDisplayName(tmuxName);
}

function sessionDisplayLabelForLegacy(row: NameableRow | null): string {
    return sessionDisplayLabel(row);
}

function archivedProjectsVisible(): boolean {
    return uiPrefs.archivedProjectsVisible;
}

function archiveSessionRecordForLegacy(sessionUuid: string | null): Promise<void> {
    return archiveSessionRecord(sessionUuid, recentHost, t);
}

function forkSessionForLegacy(tmuxName: string | null): Promise<void> {
    return forkSession(tmuxName, recentHost, t);
}

function restartRecentSessionForLegacy(
    opts: Partial<RestartOptions> | null,
): Promise<void> {
    return restartRecentSession(opts, recentHost, t);
}

function loadProjectsForLegacy(
    includeArchived: boolean,
): Promise<{ ok: boolean; error: string | null }> {
    return sessionStore.loadProjects(!!includeArchived, t);
}

function loadRunningSessionsForLegacy(): Promise<void> {
    return sessionStore.loadRunningSessions(t);
}

function loadSessionAttributionForLegacy(): Promise<void> {
    return sessionStore.loadSessionAttribution(t);
}

function workStampForLegacy(row: RunningSessionRow | null): string | null {
    return workStampFor(row, sessionStore.workStampByName);
}

function startSessionPolling(tick: () => Promise<unknown> | unknown): void {
    sessionStore.startPolling({ tick });
}

function stopSessionPolling(): void {
    sessionStore.stopPolling();
}

function renderProbe(status?: string | null, signals?: StatusSignals | null): string {
    const s: StatusSignals = signals || {};
    const host = document.createElement('div');
    const component = mount(StatusLed, {
        target: host,
        props: {
            status: status ?? null,
            unread: !!s.unread,
            startupGate: s.startup_gate ?? null,
            statusSource: s.status_source ?? null,
            activityHint: s.activity_hint ?? null,
            size: s.size ?? null,
        },
    });
    const html = host.innerHTML;
    unmount(component, { outro: false });
    return html;
}



function createHost(): CreateHost {
    return browserCreateHost();
}

async function startNewClaudeProjectForLegacy(): Promise<void> {
    await startNewClaudeProjectFlow(createHost(), browserModals(), t);
}

/* already exists */
async function startSessionInExistingProjectForLegacy(): Promise<void> {
    await startSessionInExistingProjectFlow(createHost(), browserModals(), t);
}

async function createNewSessionForLegacy(agentType: string | null = null): Promise<void> {
    await createProjectFlow(createHost(), browserModals(), t, agentType);
}

async function createConsoleSessionForLegacy(
    options: { workingDir?: string | null } | null = null,
): Promise<void> {
    await createConsoleFlow(createHost(), t, options?.workingDir || '~');
}

async function cloneFromGithubForLegacy(): Promise<void> {
    await cloneFromGithubFlow(createHost(), browserModals(), t);
}

async function openProjectFromFolderForLegacy(): Promise<void> {
    await openProjectFromFolderFlow(createHost(), browserModals(), t);
}

async function archiveProjectForLegacy(projectName: string): Promise<void> {
    await archiveProjectFlow(createHost(), t, projectName);
}

async function unarchiveProjectForLegacy(projectName: string): Promise<void> {
    await unarchiveProjectFlow(createHost(), t, projectName);
}

async function editProjectForLegacy(project: ProjectRow): Promise<void> {
    await editProjectFlow(createHost(), browserModals(), t, project);
}

function confirmForLegacy(
    title: string,
    message: string,
    details: string | null = null,
    primaryLabel = 'confirm',
    secondaryLabel = 'cancel',
): Promise<boolean> {
    return createHost().confirm(title, message, details, primaryLabel, secondaryLabel);
}



function navHost() {
    return browserNavHost();
}

async function openRunningSession(sessionId: string, tmuxName: string): Promise<void> {
    const id = String(sessionId || '').trim();
    const name = String(tmuxName || '').trim();
    if (!id && !name) return;
    let row = id
        ? sessionStore.runningSessions.find((candidate) => candidate.session_id === id)
        : undefined;
    if (!row && id) {
        await sessionStore.loadRunningSessions(t);
        row = sessionStore.runningSessions.find((candidate) => candidate.session_id === id);
    }
    if (row?.is_active) {
        await returnToActiveSessionFlow(row.session_id ?? null, browserNavHost(), t);
        return;
    }
    if (!name) return;
    await attachRunningSessionFlow(name, browserNavHost(), t);
}

function initHomeScreen(): void {
    mountHomeScreen();
}

async function loadHomeScreen(): Promise<void> {
    const running = sessionStore.loadRunningSessions(t);
    refreshLaunchpadPanels();
    const result = await sessionStore.loadProjects(uiPrefs.archivedProjectsVisible, t);
    if (!result.ok && result.error) showHomeError(result.error, t);
    void running;
}

const CloudeWeb = {
    openForkPicker,
    ledHtml: ledHtmlForStatus,
    led,
    labelFor,
    labelWithSource,
    normalizeStatus,
    StatusLed,
    renderProbe,
    mountPanel,
    openSubagentList,
    openAttachmentLightbox,
    openTimerList,
    closeCatalogScreen,
    closeWarezScreen,
    closeEliteScreen,
    openCatalogScreen,
    closeLedgerScreen,
    openLedgerScreen,
    openThemesScreen,
    closeThemesScreen,
    closeBrowserScreen,
    browsers: browserBridge,
    layouts: layoutsBridge,
    addToMenu: addToMenuBridge,
    rowMenu: rowMenuBridge,
    openMenu: { claim: claimOpenMenu },
    placeMenu,
    sendTo: sendToBridge,
    moveToFolder: moveToFolderBridge,
    sidebarShell,
    showPath,
    openBlueprintsScreen,
    closeBlueprintsScreen,
    openBlueprintPicker,
    askLeaderConfirm,
    openPluginsScreen,
    closePluginsScreen,
    closeSkillsManagerScreen,
    openWidgetsScreen,
    closeWidgetsScreen,
    openLaunchPicker,
    mountLaunchChoice,
    openWrappersScreen: () => openSettingsSection('launch_profiles'),
    closeWrappersScreen: closeSettingsScreen,
    openHostsScreen,
    closeHostsScreen,
    openSettingsScreen,
    closeSettingsScreen,
    openAccountScreen,
    closeAccountScreen,
    /* running sessions */
    openSessionsScreen,
    closeSessionsScreen,
    openDocsScreen,
    closeDocsScreen,
    closeChangelogScreen,
    openLogsScreen,
    closeLogsScreen,
    closeWarroomScreen,
    closeHuddleAgentScreen,
    closeHuddleSwarmScreen,
    closeDashboardsScreen,
    openAutomationsScreen,
    closeAutomationsScreen,
    scheduleThis: openScheduleThis,
    closeModsScreen,
    namesMenuPage: (hash: string | null | undefined): boolean => pageOfHash(hash) !== null,
    blueprints: blueprintsLegacyBridge,
    autoSleep: autoSleepBridge,
    mountHelpReleases,
    unmountHelpReleases,
    mountHelpFeatures,
    unmountHelpFeatures,
    launchpad: {
        mountAttributionPrompt,
        mountRecentSessions,
        mountProjectTree,
        mountRunningSessions,
        displayNameFor: displayNameForLegacy,
        sessionDisplayLabel: sessionDisplayLabelForLegacy,
        archivedProjectsVisible,
        sessions: sessionStore,
        loadProjects: loadProjectsForLegacy,
        loadRunningSessions: loadRunningSessionsForLegacy,
        loadSessionAttribution: loadSessionAttributionForLegacy,
        startSessionPolling,
        stopSessionPolling,
        workStampFor: workStampForLegacy,
        archiveSessionRecord: archiveSessionRecordForLegacy,
        forkSession: forkSessionForLegacy,
        restartRecentSession: restartRecentSessionForLegacy,
        /* nothing at all */
        startNewClaudeProject: startNewClaudeProjectForLegacy,
        startSessionInExistingProject: startSessionInExistingProjectForLegacy,
        createNewSession: createNewSessionForLegacy,
        createConsoleSession: createConsoleSessionForLegacy,
        cloneFromGithub: cloneFromGithubForLegacy,
        openProjectFromFolder: openProjectFromFolderForLegacy,
        archiveProject: archiveProjectForLegacy,
        unarchiveProject: unarchiveProjectForLegacy,
        editProject: editProjectForLegacy,
        confirm: confirmForLegacy,
        mountHomeScreen: initHomeScreen,
        unmountHomeScreen,
        openRunningSession,
        refreshLaunchpadPanels,
        loadHomeScreen,
        openProjectByName: (name: string) => openProjectByNameFlow(name, navHost(), t),
        selectProject: (project: ProjectRow, choice?: Record<string, unknown> | null) =>
            selectProjectFlow(project, navHost(), t, choice),
        detachAndOpenProject: (project: ProjectRow) =>
            detachAndOpenProjectFlow(project, navHost(), t),
        detachAndCreateNew: (agentType: string | null) =>
            detachAndCreateNewFlow(agentType, navHost(), t, createNewSessionForLegacy),
        connectToExistingSession: () => connectToExistingSessionFlow(navHost(), t),
        explainRefusedProject,
        isResolvingDeepLink,
        updateStatus,
        showError: (message: string) => showHomeError(message, t),
        terminalDims: () => navHost().terminalDims(),
    },
    sessionCardMenuItems,
    runSessionCardAction,
    runCplugCardAction,
    i18n: { t, setLocale, currentLocale, instance: i18n },
    sessionSummaryLabel: summaryLabel,
    mountTerminalSearch,
    unmountTerminalSearch,

    toggleSessionNotes,

    iconSvg: iconSvgString,
    openTerminalSearch,
    toggleTerminalSearch,
    terminalSearchIsOpen,
    showTerminalStartupNotice,
    clearTerminalStartupNotice,
    showTerminalSizeNotice,
    clearTerminalSizeNotice,
    tabDrag: { begin: beginDrawerTabDrag },
    layoutEditor: layoutEditorBridge,
    openTerminalEmpty,
    closeTerminalEmpty,
    mountSlashFavorites,
    setSlashFavorites,
    resumeHomePolls,
    pauseHomePolls,
    mountTerminalGrid,
    unmountTerminalGrid,
    mountTerminalPhoneTabs,
    unmountTerminalPhoneTabs,
    showSoloPanel,
    hideSoloPanel,
    openTerminalComponents,
    closeTerminalComponents,
    terminalComponentsOpen,
    fileDrawer: { mountHeader: mountFileDrawerHeader, mountGit: mountFileDrawerGit, showCell: showFilesCell, openFile: openFromDrawer },
    iconPicker: { mount: mountIconPicker, unmount: unmountIconPicker },
    rightDrawer: rightDrawerApi,
    sizeMasterHolder: (sessionId: string): string | null => sizeMasters[sessionId] ?? null,
    sizeMasterClientId: thisTabId,
    claimSizeMaster,
    releaseSizeMaster,
    masterAllEnabled: (): boolean => masterAll.enabled,
    setMasterAll,
    openApprovalFor,
} as const;

declare global {
    interface Window {
        CloudeWeb: typeof CloudeWeb;
    }
}

if (window.CloudeWeb) {
    throw new Error('window.CloudeWeb is already defined - two bundles are loaded');
}
window.CloudeWeb = CloudeWeb;
installRowMenuOpener();

bootListingPush();
bootResourcePush();
startOutbox();
bootNativeShell();
installNotifyScreen();
installNotifyMute();
startPresenceBeacon();
mountDrawerHeader();
publishTerminalProvider();
bootDrawer();

publishLaunchpadShim({
    launchpadScreen,
    init: initHomeScreen,
    loadProjects: loadHomeScreen,
    loadRunningSessions: () => sessionStore.loadRunningSessions(t),
    openProjectByName: (name: string) => openProjectByNameFlow(name, browserNavHost(), t),
    showError: (message: string) => showHomeError(message, t),
    selectProject: (project: ProjectRow, choice?: Record<string, unknown> | null) =>
        selectProjectFlow(project, browserNavHost(), t, choice),
});

mountTerminalSearch();

mountSessionNotes();
mountAppAlerts();
startApprovals();
wireAskOpeners();
startMenuCommands();
startCplugs();
mountTerminalFoot();
followActiveTerminal();
startMasterAll();
installSignInModal();
installWelcome();
installRefusalHandler();

mountDrawerTabs();
initMenuPageShell();
initHomeInMain();
ensurePanel('menu-page-bar', MenuPageBar, {});
mountLayoutEditor();

wireCatalogDeepLink();
wireLedgerDeepLink();
wireThemesDeepLink();
wireBrowserDeepLink();
guardUnload();
watchOrphans();
wireBlueprintsDeepLink();
wirePluginsDeepLink();
wireWidgetsDeepLink();
wireSettingsDeepLink();
installSettingsShortcut();
wireAccountDeepLink();
wireSessionsDeepLinks();
wireInfoPageDeepLinks();
wireLogsDeepLink();
wireWarroomDeepLink();
wireHuddleAgentDeepLink();
wireHuddleSwarmDeepLink();
wireDashboardsDeepLink();
wireAutomationsDeepLink();
wireModsDeepLink();
wireEliteDeepLink();
wireHostsDeepLink();
themeFavorites.start();
startArrangementSync();
startHomeSync();
startWarroomSync();
void runLayoutMigration();
startContextLinks();
startAutoSleep();
startSessionDiedFrames();
startCrosstalkCards();
followBrowserSelect();
followUiShow();
startActivityReport();
startGoneReport();

mountSpectateIfNeeded();

mountVersionBanner();
mountPanel('relay-consent-container', RelayConsentPopup, {});
mountPanel('pack-op-toast-container', PackOpToast, {});
mountPanel('cplug-overlay-container', OverlayRoot, {});

// nothing at all
void startPerfOverlay();
