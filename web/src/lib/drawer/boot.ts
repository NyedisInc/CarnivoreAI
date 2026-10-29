/* failed to load */
import * as Arrangement from './arrangement';
import { isDragging as sectionDragging } from '../sidebar-shell/section-drag';
import * as Bar from './bar';
import * as Bucketing from './bucketing';
import { pageSectionMeta } from './page-sections';
import * as Density from './density';
import { SessionSidebarController } from './controller';
import { setDrawerController } from './controller-ref';
import { pageWindow } from './env';
import * as Fetch from './fetch';
import * as GroupOrder from './group-order';
import * as Membership from './group-membership';
import * as GroupStore from './group-store';
import * as Pin from './pin';
import * as Search from './search';
import * as Store from './store';
import * as Keys from './store-keys';
import * as Sync from './sync';
import { watchViewClass } from './view-class';
import { reapplyForViewClass } from './class-flip';
import * as StatsVisibility from './stats-visibility.svelte';
import * as SectionVisibility from './section-visibility.svelte';
import * as ClosedVisibility from './closed-visibility.svelte';
import { openColorMenu } from '../sidebar-shell/heading-color-actions';
import { WakeFocus } from '../sidebar-shell/wake-focus';

let controller: SessionSidebarController | null = null;

export function sidebarController(): SessionSidebarController | null {
    return controller;
}

function storeFacade(): Record<string, unknown> {
    return {
        load: Store.load, current: Store.current, save: Store.save, onSaved: Store.onSaved,
        isPinned: Store.isPinned, isCollapsed: Store.isCollapsed, toggleCollapsed: Store.toggleCollapsed,
        readCollapsed: Store.readCollapsed, readIds: Store.readIds, dedupe: Store.dedupe,
        isNameArray: Store.isNameArray, isFoldKey: Keys.isFoldKey, readBands: Store.readBands,
        isBandOrderKey: Keys.isBandOrderKey, bandOrder: Store.bandOrder, saveBandOrder: Store.saveBandOrder,
        MAX_BAND_ORDERS: Store.MAX_BAND_ORDERS, STORAGE_KEY: Store.STORAGE_KEY, VERSION: Store.VERSION,
        MAX_REMEMBERED: Store.MAX_REMEMBERED, GROUP_KEYS: Keys.GROUP_KEYS,
        GROUP_FOLD_PREFIX: Keys.GROUP_FOLD_PREFIX, PROJECT_FOLD_PREFIX: Keys.PROJECT_FOLD_PREFIX,
        ROGUE_FOLD_KEY: Keys.ROGUE_FOLD_KEY, KIND_FOLD_KEYS: Keys.KIND_FOLD_KEYS,
        LEDGER_FOLD_KEYS: Keys.LEDGER_FOLD_KEYS, LAYOUT_FOLD_KEY: Keys.LAYOUT_FOLD_KEY,
        LAYOUT_ITEM_FOLD_PREFIX: Keys.LAYOUT_ITEM_FOLD_PREFIX, MAX_FOLDS: Keys.MAX_FOLDS,
    };
}

function arrangementFacade(): Record<string, unknown> {
    return {
        load: Store.load, current: Store.current, save: Store.save, isPinned: Store.isPinned,
        isCollapsed: Store.isCollapsed, toggleCollapsed: Store.toggleCollapsed,
        readCollapsed: Store.readCollapsed, STORAGE_KEY: Store.STORAGE_KEY, VERSION: Store.VERSION,
        MAX_REMEMBERED: Store.MAX_REMEMBERED, GROUP_KEYS: Keys.GROUP_KEYS,
        arrange: Arrangement.arrange, mergeOrder: Arrangement.mergeOrder, togglePin: Arrangement.togglePin,
        move: Arrangement.move, placeAt: Arrangement.placeAt, sameOrder: Arrangement.sameOrder,
        groupStore: Arrangement.groupStore, mergeInto: Arrangement.mergeInto,
        orderBand: Arrangement.orderBand, placeInBand: Arrangement.placeInBand,
        moveInBand: Arrangement.moveInBand,
    };
}

export function publishDrawer(root: Record<string, unknown>, ctrl: SessionSidebarController | null): void {
    if (ctrl) root.SessionSidebar = ctrl;
    root.WakeFocus = WakeFocus;
    root.SessionSidebarStore = storeFacade();
    root.SessionSidebarArrangement = arrangementFacade();
    root.SessionSidebarSectionDrag = { isDragging: sectionDragging };
    root.SessionSidebarGroupStore = { ...GroupStore };
    root.SessionSidebarGroupOrder = { nextOrder: GroupOrder.nextOrder, commitMemberOrder: GroupOrder.commitMemberOrder };
    root.SessionSidebarGroupsSearch = {
        narrow: Bucketing.narrow, filteredBandSections: Bucketing.filteredBandSections,
        filteredProjectBuckets: Bucketing.filteredProjectBuckets, keepBandSection: Bucketing.keepBandSection,
    };
    root.SessionSidebarKindGroups = {
        kindOf: Bucketing.kindOf, isAgentKind: Bucketing.isAgentKind, isTerminal: Bucketing.isTerminal,
        isBrowser: Bucketing.isBrowser, pageSectionOf: Bucketing.pageSectionOf, terminalRows: Bucketing.terminalRows, folderLabel: Bucketing.folderLabel,
        BAND_TERMINALS: Bucketing.BAND_TERMINALS, BAND_BROWSERS: Bucketing.BAND_BROWSERS,
        pageSectionIcon: (key: string): string | null => pageSectionMeta(key)?.icon ?? null,
    };
    root.SessionSidebarFetch = {
        load: Fetch.load, mergeLiveRow: Fetch.mergeLiveRow, defaultSort: Fetch.defaultSort,
        statusOf: Fetch.statusOf, workStampIndex: Fetch.workStampIndex, workAttr: Fetch.workAttr,
    };
    root.SessionSidebarGroupMembership = {
        uuidOfName: Membership.uuidOfName, groupOf: Membership.groupOf, memberRank: Membership.memberRank,
    };
    root.SessionSidebarDensity = {
        init: Density.init, apply: Density.apply, setMode: Density.setMode, currentMode: Density.currentMode,
        STORAGE_KEY: Density.STORAGE_KEY, MODES: Density.MODES, DEFAULT_MODE: Density.DEFAULT_MODE,
        MOBILE_STORAGE_KEY: Density.MOBILE_STORAGE_KEY, MOBILE_PREFERENCE_FIELD: Density.MOBILE_PREFERENCE_FIELD,
    };
    root.SessionSidebarColorMenu = { open: openColorMenu };
    root.SessionSidebarSearch = {
        getQuery: Search.getQuery, filterActive: Search.filterActive, setQuery: Search.setQuery, matchesRow: Search.matchesRow,
        matchesLabel: Search.matchesLabel, noMatchesHtml: Search.noMatchesHtml, normalize: Search.normalize,
    };
    root.SessionSidebarPin = {
        init: Pin.init, apply: Pin.apply, closeAfterSwitch: Pin.closeAfterSwitch,
        isEffectivelyPinned: Pin.isEffectivelyPinned, isMobile: Pin.isMobile, opensFrom: Pin.opensFrom,
        RAIL_CLASS: Pin.RAIL_CLASS, MOBILE_MAX_PX: Pin.MOBILE_MAX_PX,
    };
    root.SessionSidebarBar = { run: Bar.run, paint: Bar.paint };
}

export function bootDrawer(): SessionSidebarController {
    if (controller) return controller;
    const ctrl = new SessionSidebarController();
    controller = ctrl;
    setDrawerController(ctrl);
    publishDrawer(pageWindow(), ctrl);
    Sync.start();
    watchViewClass(() => reapplyForViewClass(ctrl));
    //  hidden 
    if (typeof document !== 'undefined' && typeof document.addEventListener === 'function') {
        document.addEventListener('visibilitychange', () => {
            if (!document.hidden) void ctrl.refreshNow();
        });
    }
    return ctrl;
}
