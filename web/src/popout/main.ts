/* the home screen */
import '../cplugs/host/early-kinds';
import '../app.css';
import '../opscenter/app.css';
import './popout.css';
import '../lib/tooltip/tooltip.css';
import { installSharedTooltip } from '../lib/tooltip/tooltip';
import { bootPopoutLive } from './live';
import { mountPanel } from '../lib/mount';
import OpscenterApp from '../opscenter/App.svelte';
import { t } from '../lib/i18n/index.svelte';
import { manifestById } from '../opscenter/widgets/core-manifests';
import { popoutWidgetFor } from '../cplugs/host/popout-widgets';
import SingleWidget from './SingleWidget.svelte';
import AgentPopout from './AgentPopout.svelte';
import TabPopout from './TabPopout.svelte';
import BrowserPopout from './BrowserPopout.svelte';
import { popoutTab } from '../lib/dynamic-tabs/popout-tabs';
import { tabFromSearch, tabGeometryKey } from '../lib/dynamic-tabs/tab-popout';
import { agentFromSearch, agentGeometryKey, browserFromSearch, BROWSER_GEOMETRY_KEY, dashboardFromSearch, dashboardOpensEditing, placementFromSearch, rememberGeometry, widgetFromSearch, widgetGeometryKey, DASHBOARD_GEOMETRY_KEY, POPOUT_GEOMETRY_KEY, WALLBOARD_GEOMETRY_KEY, POPOUT_SAVE_DELAY_MS } from './popout';
import { startHomeSync } from '../opscenter/engine/home-sync.svelte';
import { isWallboardSearch } from '../opscenter/engine/wallboard';
import { BOARD_PARAM } from '../opscenter/engine/home-boards';
import { bootListingPush } from '../lib/listing-push/boot';
import { stopHomeCacheWrites } from '../opscenter/engine/persist';
import { startPopoutEditor } from '../opscenter/layout-editor/popout-editor';

export const POPOUT_CONTAINER = 'popout-screen';

function bootWidgetPopout(widget: string): boolean {
    const titleKey = manifestById(widget)?.titleKey ?? popoutWidgetFor(widget)?.widget.meta.titleKey;
    document.title = titleKey ? t(titleKey) : t('opscenter.popout.title');
    if (mountPanel(POPOUT_CONTAINER, SingleWidget as never, { widget, placement: placementFromSearch(window.location.search) }) === null) return false;
    rememberGeometry(window, POPOUT_SAVE_DELAY_MS, widgetGeometryKey(widget));
    return true;
}

function bootAgentPopout(agent: number): boolean {
    document.title = t('cplug.huddle.swarm.drawer.label');
    if (mountPanel(POPOUT_CONTAINER, AgentPopout as never, { agent }) === null) return false;
    rememberGeometry(window, POPOUT_SAVE_DELAY_MS, agentGeometryKey(agent));
    return true;
}

function bootTabPopout(tab: string): boolean {
    const def = popoutTab(tab);
    document.title = def ? t(def.labelKey, { count: 0 }) : t('opscenter.popout.title');
    if (mountPanel(POPOUT_CONTAINER, TabPopout as never, { tab }) === null) return false;
    rememberGeometry(window, POPOUT_SAVE_DELAY_MS, tabGeometryKey(tab));
    return true;
}

function bootBrowserPopout(browser: string): boolean {
    document.title = t('browser.page');
    if (mountPanel(POPOUT_CONTAINER, BrowserPopout as never, { browser }) === null) return false;
    rememberGeometry(window, POPOUT_SAVE_DELAY_MS, BROWSER_GEOMETRY_KEY);
    return true;
}

export function bootPopout(): boolean {
    const tab = tabFromSearch(window.location.search);
    if (tab !== null) return bootTabPopout(tab);
    const agent = agentFromSearch(window.location.search);
    if (agent !== null) return bootAgentPopout(agent);
    const browser = browserFromSearch(window.location.search);
    if (browser !== null) return bootBrowserPopout(browser);
    const widget = widgetFromSearch(window.location.search);
    if (widget !== null) return bootWidgetPopout(widget);
    const wallboard = isWallboardSearch(window.location.search);
    const dashboard = dashboardFromSearch(window.location.search);
    if (dashboard !== null) stopHomeCacheWrites();
    document.title = t(wallboard ? 'opscenter.wallboard.title' : dashboard ? 'dashboards.popout_title' : 'opscenter.popout.title');
    if (dashboard !== null) startPopoutEditor(document, dashboardOpensEditing(window.location.search));
    const mounted = mountPanel(POPOUT_CONTAINER, OpscenterApp as never, { popout: true, wallboard });
    if (mounted === null) return false;
    rememberGeometry(window, POPOUT_SAVE_DELAY_MS, wallboard ? WALLBOARD_GEOMETRY_KEY : dashboard ? DASHBOARD_GEOMETRY_KEY : POPOUT_GEOMETRY_KEY);
    startHomeSync({ popout: true, board: new URLSearchParams(window.location.search).get(BOARD_PARAM), edit: dashboard !== null });
    return true;
}

// nothing at all
installSharedTooltip();

bootListingPush();
bootPopoutLive();
bootPopout();
