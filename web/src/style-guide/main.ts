import './offline';
import type { Component } from 'svelte';
import { mountPanel } from '../lib/mount';
import { PLUGIN_SPECIMENS } from '../cplugs/style-guide';
import { pluginGuideEntries } from './plugin-entries';
import { installSharedTooltip } from '../lib/tooltip/tooltip';
import LedMatrix from './specimens/LedMatrix.svelte';
import AgentMarksRow from './specimens/AgentMarksRow.svelte';
import BotCycleMarkRow from './specimens/BotCycleMarkRow.svelte';
import IconSet from './specimens/IconSet.svelte';
import GlyphSet from './specimens/GlyphSet.svelte';
import TabsDemo from './specimens/TabsDemo.svelte';
import PageTabsDemo from './specimens/PageTabsDemo.svelte';
import OpsPrimitives from './specimens/OpsPrimitives.svelte';
import Pills from './specimens/Pills.svelte';
import Modals from './specimens/Modals.svelte';
import AnchoredPopupDemo from './specimens/AnchoredPopupDemo.svelte';
import Catalog from './specimens/Catalog.svelte';
import Ledger from './specimens/Ledger.svelte';
import CellFrameDemo from './specimens/CellFrameDemo.svelte';
import PlacementHeadDemo from './specimens/PlacementHeadDemo.svelte';
import BarSizesDemo from './specimens/BarSizesDemo.svelte';
import BarVisibilityDemo from './specimens/BarVisibilityDemo.svelte';
import PinnedPanelDemo from './specimens/PinnedPanelDemo.svelte';
import Meters from './specimens/Meters.svelte';
import PackDemo from './specimens/PackDemo.svelte';
import PackRowsDemo from './specimens/PackRowsDemo.svelte';
import AccountChipDemo from './specimens/AccountChipDemo.svelte';
import DrawerChromeDemo from './specimens/DrawerChromeDemo.svelte';
import ManagerFrameDemo from './specimens/ManagerFrameDemo.svelte';
import RankPanelDemo from './specimens/RankPanelDemo.svelte';
import PageKitDemo from './specimens/PageKitDemo.svelte';
import IconPickerDemo from './specimens/IconPickerDemo.svelte';
import PluginsScreen from '../lib/plugins-page/PluginsScreen.svelte';
import WidgetsScreen from '../lib/widgets-page/WidgetsScreen.svelte';
import { pluginsSpecimenAdapter, pluginsSpecimenCatalog } from './specimens/plugins-fixture';
import { specimenSettingsFor, widgetsSpecimenAdapter } from './specimens/widgets-fixture';
import SettingsFormDemo from './specimens/SettingsFormDemo.svelte';
import PickerDemo from './specimens/PickerDemo.svelte';
import LaunchChoiceDemo from './specimens/LaunchChoiceDemo.svelte';
import CrosstalkCard from '../lib/crosstalk/CrosstalkCard.svelte';
import ApprovalCards from './specimens/ApprovalCards.svelte';
import QuestionCards from './specimens/QuestionCards.svelte';
import AskFormSpecimen from './specimens/AskForm.svelte';
import BaseThemes from './specimens/BaseThemes.svelte';
import ContrastMatrix from './specimens/ContrastMatrix.svelte';
import BaseComponents from './specimens/BaseComponents.svelte';
import BaseComponentsThemes from './specimens/BaseComponentsThemes.svelte';
import TaskWrapperDemo from './specimens/TaskWrapperDemo.svelte';
import BaseControls from './specimens/BaseControls.svelte';
import StatWidgets from './specimens/StatWidgets.svelte';
import StatWidgetsThemes from './specimens/StatWidgetsThemes.svelte';
import QuestionCardDemo from './specimens/QuestionCardDemo.svelte';
import QuestionCardToday from './specimens/QuestionCardToday.svelte';
import BaseElements from './specimens/BaseElements.svelte';
import BaseElementsThemes from './specimens/BaseElementsThemes.svelte';
import ReviewPanel from './specimens/ReviewPanel.svelte';
import AutomationsPageDemo from './specimens/AutomationsPageDemo.svelte';

interface Specimen {
    id: string;
    component: Component<Record<string, unknown>>;
    props?: Record<string, unknown>;
}

function as(component: unknown): Component<Record<string, unknown>> {
    return component as Component<Record<string, unknown>>;
}

export const SPECIMENS: readonly Specimen[] = [
    { id: 'sg-live-crosstalk-card', component: as(CrosstalkCard), props: { sessionId: 'receiver-1', message: {
        id: 'sg-message-1', source: 'crosstalk', thread: 'sg-thread-1', sender_id: 'sender-1', sender_uuid: null,
        sender_name: 'build-agent', sender_provider: 'claude', sender_model: 'sonnet',
        receiver_id: 'receiver-1', receiver_uuid: null, receiver_name: 'test-agent', receiver_provider: 'codex', receiver_model: 'gpt-6-sol',
        text: 'check the browser behavior after the build.\nconfirm the terminal line is still readable.\nreport any theme contrast issue.\nthen send the result.',
        status: 'delivered', created_at: 1780462800,
    } } },
    { id: 'sg-live-question-cards', component: as(QuestionCards) },
    { id: 'sg-live-approval-cards', component: as(ApprovalCards) },
    { id: 'sg-live-ask-form', component: as(AskFormSpecimen) },
    { id: 'sg-live-led-matrix', component: as(LedMatrix) },
    ...PLUGIN_SPECIMENS,
    { id: 'sg-live-agent-marks', component: as(AgentMarksRow) },
    { id: 'sg-live-bot-cycle-mark', component: as(BotCycleMarkRow) },
    { id: 'sg-live-icons', component: as(IconSet) },
    { id: 'sg-live-glyphs', component: as(GlyphSet) },
    { id: 'sg-live-icon-picker', component: as(IconPickerDemo), props: { initial: 'folder', tone: '--oc-green' } },
    { id: 'sg-live-icon-picker-none', component: as(IconPickerDemo), props: { initial: null, tone: '--oc-violet' } },
    { id: 'sg-live-page-tabs', component: as(PageTabsDemo) },
    { id: 'sg-live-page-tabs-joined', component: as(PageTabsDemo), props: { joined: true } },
    { id: 'sg-live-page-tabs-collapse-wide', component: as(PageTabsDemo), props: { collapse: true } },
    { id: 'sg-live-page-tabs-collapse-narrow', component: as(PageTabsDemo), props: { collapse: true } },
    { id: 'sg-live-page-tabs-many', component: as(PageTabsDemo), props: { many: true } },
    { id: 'sg-live-tabs', component: as(TabsDemo), props: { variant: 'desktop' } },
    { id: 'sg-live-tabs-menu', component: as(TabsDemo), props: { variant: 'desktop' } },
    { id: 'sg-live-tabs-touch', component: as(TabsDemo), props: { variant: 'touch' } },
    { id: 'sg-live-tabs-drag', component: as(TabsDemo), props: { variant: 'dragging' } },
    { id: 'sg-live-status-pills', component: as(OpsPrimitives), props: { part: 'pills' } },
    { id: 'sg-live-sparkline', component: as(OpsPrimitives), props: { part: 'spark' } },
    { id: 'sg-live-sort', component: as(OpsPrimitives), props: { part: 'sort' } },
    { id: 'sg-live-table', component: as(OpsPrimitives), props: { part: 'table' } },
    { id: 'sg-live-family-pills', component: as(Pills) },
    { id: 'sg-live-modals', component: as(Modals) },
    { id: 'sg-live-anchored-popup', component: as(AnchoredPopupDemo) },
    { id: 'sg-live-catalog-toolbar', component: as(Catalog), props: { part: 'toolbar' } },
    { id: 'sg-live-catalog-cards', component: as(Catalog), props: { part: 'cards' } },
    { id: 'sg-live-catalog-packs', component: as(Catalog), props: { part: 'packs' } },
    { id: 'sg-live-catalog-kinds', component: as(Catalog), props: { part: 'kinds' } },
    { id: 'sg-live-catalog-grade', component: as(Catalog), props: { part: 'grade' } },
    { id: 'sg-live-field', component: as(Catalog), props: { part: 'toolbar' } },
    { id: 'sg-live-toggle', component: as(Catalog), props: { part: 'toggle' } },
    { id: 'sg-live-ledger', component: as(Ledger) },
    { id: 'sg-live-manager', component: as(ManagerFrameDemo), props: { part: 'ready' } },
    { id: 'sg-live-manager-loading', component: as(ManagerFrameDemo), props: { part: 'loading' } },
    { id: 'sg-live-manager-empty', component: as(ManagerFrameDemo), props: { part: 'empty' } },
    { id: 'sg-live-manager-error', component: as(ManagerFrameDemo), props: { part: 'error' } },
    { id: 'sg-live-manager-share', component: as(ManagerFrameDemo), props: { part: 'ready', share: true } },
    { id: 'sg-live-manager-limits', component: as(ManagerFrameDemo), props: { part: 'ready', limits: true } },
    { id: 'sg-live-rank-panel', component: as(RankPanelDemo) },
    { id: 'sg-live-page-toolbar', component: as(PageKitDemo), props: { part: 'toolbar' } },
    { id: 'sg-live-highlight-tiles', component: as(PageKitDemo), props: { part: 'tiles' } },
    { id: 'sg-live-highlight-pair', component: as(PageKitDemo), props: { part: 'pair' } },
    { id: 'sg-live-plugins-page', component: as(PluginsScreen), props: { embedded: true, adapter: pluginsSpecimenAdapter, catalog: pluginsSpecimenCatalog } },
    { id: 'sg-live-widgets-page', component: as(WidgetsScreen), props: { embedded: true, previews: false, adapter: widgetsSpecimenAdapter, settingsFor: specimenSettingsFor } },
    { id: 'sg-live-settings-form', component: as(SettingsFormDemo) },
    { id: 'sg-live-picker', component: as(PickerDemo) },
    { id: 'sg-live-choice', component: as(LaunchChoiceDemo), props: { part: 'profile' } },
    { id: 'sg-live-launch-choice', component: as(LaunchChoiceDemo), props: { part: 'full' } },
    { id: 'sg-live-pack-computers', component: as(PackDemo), props: { part: 'computers' } },
    { id: 'sg-live-pack-meters', component: as(PackDemo), props: { part: 'meters' } },
    { id: 'sg-live-pack-marks', component: as(PackDemo), props: { part: 'marks' } },
    { id: 'sg-live-pack-rows', component: as(PackRowsDemo) },
    { id: 'sg-live-meters-drawer', component: as(Meters), props: { part: 'drawer' } },
    { id: 'sg-live-account-chip', component: as(AccountChipDemo) },
    { id: 'sg-live-drawer-header', component: as(DrawerChromeDemo), props: { part: 'header' } },
    { id: 'sg-live-drawer-stats', component: as(DrawerChromeDemo), props: { part: 'stats' } },
    { id: 'sg-live-meters-foot', component: as(Meters), props: { part: 'foot' } },
    { id: 'sg-live-cellframe', component: as(CellFrameDemo), props: { slot: 'notes' } },
    { id: 'sg-live-bar-sizes', component: as(BarSizesDemo) },
    { id: 'sg-live-bar-visibility', component: as(BarVisibilityDemo) },
    { id: 'sg-live-pinned-panel', component: as(PinnedPanelDemo) },
    { id: 'sg-live-cellframe-count', component: as(CellFrameDemo), props: { slot: 'closed-sessions', count: 12 } },
    { id: 'sg-live-widget-head-sort', component: as(CellFrameDemo), props: { slot: 'projects', sortGroup: true } },
    { id: 'sg-live-placement-head', component: as(PlacementHeadDemo) },
    { id: 'sg-live-base-themes', component: as(BaseThemes) },
    { id: 'sg-live-contrast', component: as(ContrastMatrix) },
    { id: 'sg-live-base-components', component: as(BaseComponents) },
    { id: 'sg-live-base-components-themes', component: as(BaseComponentsThemes) },
    { id: 'sg-live-task-wrapper', component: as(TaskWrapperDemo) },
    { id: 'sg-live-task-wrapper-narrow', component: as(TaskWrapperDemo) },
    { id: 'sg-live-base-controls', component: as(BaseControls) },
    { id: 'sg-live-stat-widgets', component: as(StatWidgets) },
    { id: 'sg-live-stat-widgets-themes', component: as(StatWidgetsThemes) },
    { id: 'sg-live-question-card-demo', component: as(QuestionCardDemo) },
    { id: 'sg-live-question-card-demo-narrow', component: as(QuestionCardDemo) },
    { id: 'sg-live-question-card-today', component: as(QuestionCardToday) },
    { id: 'sg-live-base-elements', component: as(BaseElements) },
    { id: 'sg-live-base-elements-themes', component: as(BaseElementsThemes) },
    { id: 'sg-live-review', component: as(ReviewPanel) },
    { id: 'sg-live-automations-page', component: as(AutomationsPageDemo) },
];

function mountOne(spec: Specimen): void {
    const host = document.getElementById(spec.id);
    if (!host) {
        console.error('style guide: no container for specimen', spec.id);
        return;
    }
    try {
        mountPanel(spec.id, spec.component, spec.props ?? {});
        host.dataset.sgState = 'mounted';
    } catch (error) {
        host.dataset.sgState = 'error';
        const line = document.createElement('p');
        line.className = 'sg-error';
        line.textContent = `specimen failed to mount: ${String(error)}`;
        host.append(line);
        console.error('style guide: specimen failed', spec.id, error);
    }
}

function mountAll(): void {
    (window as Window & { StyleGuide?: { addPluginEntries?: (entries: unknown) => void } }).StyleGuide?.addPluginEntries?.(pluginGuideEntries());
    SPECIMENS.forEach(mountOne);
    document.documentElement.dataset.sgMounted = 'true';
}

installSharedTooltip();

const win = window as Window & { StyleGuideReady?: boolean };
if (win.StyleGuideReady) {
    mountAll();
} else {
    document.addEventListener('style-guide:ready', mountAll, { once: true });
}
