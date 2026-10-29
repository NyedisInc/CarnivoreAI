
<script lang="ts">
    import type { Translate } from '../sessions/types';
    import ToastModePanel from '../toast-mode/ToastModePanel.svelte';
    import ScreenReaderPanel from '../screen-reader/ScreenReaderPanel.svelte';
    import TimeZonePanel from '../time-zone/TimeZonePanel.svelte';
    import SettingRow from './SettingRow.svelte';
    import TextControl from './controls/TextControl.svelte';
    import EnvControl from './controls/EnvControl.svelte';
    import BindControl from './controls/BindControl.svelte';
    import SwitchControl from './controls/SwitchControl.svelte';
    import MinutesControl from './controls/MinutesControl.svelte';
    import LinkControl from './controls/LinkControl.svelte';
    import MotionPanel from './MotionPanel.svelte';
    import RowIconsPanel from './RowIconsPanel.svelte';
    import FootBarLayoutPanel from './FootBarLayoutPanel.svelte';
    import FootBarItemsPanel from './FootBarItemsPanel.svelte';
    import ThemePicker from './ThemePicker.svelte';
    import ConfigBundlePanel from './ConfigBundlePanel.svelte';
    import WebPushPanel from './WebPushPanel.svelte';
    import NativeAlertsPanel from '../native-shell/NativeAlertsPanel.svelte';
    import { inNativeShell } from '../native-shell/shell';
    import AccountBody from '../carnivore-account/AccountBody.svelte';
    import AgentGatePanel from './AgentGatePanel.svelte';
    import McpPanel from './McpPanel.svelte';
    import StatsCollectionPanel from './StatsCollectionPanel.svelte';
    import InstallReportPrivacyPanel from '../install-report/InstallReportPrivacyPanel.svelte';
    import PhoneLinkPanel from './PhoneLinkPanel.svelte';
    import ApiKeysPanel from './api-keys/ApiKeysPanel.svelte';
    import TuiCliPanel from './TuiCliPanel.svelte';
    import LogLevelPanel from './LogLevelPanel.svelte';
    import AppUpdatePanel from './AppUpdatePanel.svelte';
    import McpToolSwitchesPanel from './mcp-panel/McpToolSwitchesPanel.svelte';
    import BeastGridPanel from '../beast-mode/BeastGridPanel.svelte';
    import CustomDomain from './CustomDomain.svelte';
    import ConnectionsPanel from '../byoai/ConnectionsPanel.svelte';
    import DestinationsPanel from '../notifications/destinations/DestinationsPanel.svelte';
    import MessagingScreen from '../messaging/MessagingScreen.svelte';
    import LinkPanel from '../notifications/matrix/LinkPanel.svelte';
    import MatrixPanel from '../notifications/matrix/MatrixPanel.svelte';
    import MutesPanel from '../notifications/mute/MutesPanel.svelte';
    import SyncPanel from '../notifications/sync/SyncPanel.svelte';
    import RoutingPanel from '../byoai/RoutingPanel.svelte';
    import CallsPanel from '../byoai/CallsPanel.svelte';
    import PipelineStatusPanel from '../pipeline-status/PipelineStatusPanel.svelte';
    import DeepSearchScopePanel from './DeepSearchScopePanel.svelte';
    import { minutesRange } from './controls/minutes-range';
    import { isWideControl, type SettingDef } from './settings-registry';

    interface Props {
        def: SettingDef;
        t: Translate;
        flash?: boolean;
        solo?: boolean;
    }

    const { def, t, flash = false, solo = false }: Props = $props();

    const kind = $derived(def.control.kind);
    const inputId = $derived(`setting-input-${def.id}`);
    const note = $derived.by(() => {
        if (kind !== 'auto-sleep-minutes' && kind !== 'auto-sleep-unread-minutes') return null;
        return t('auto_sleep.minutes_range', minutesRange());
    });
    const labelFor = $derived(['text', 'secret', 'env', 'bind', 'auto-sleep-minutes', 'auto-sleep-unread-minutes'].includes(kind) ? inputId : null);
</script>

<SettingRow {def} {t} {flash} solo={solo && isWideControl(def.control)} wide={isWideControl(def.control)} inputId={labelFor} {note}>
    {#if def.control.kind === 'text' || def.control.kind === 'secret'}
        <TextControl {def} {t} {inputId} />
    {:else if def.control.kind === 'env'}
        <EnvControl {t} {inputId} />
    {:else if def.control.kind === 'bind'}
        <BindControl {t} {inputId} />
    {:else if def.control.kind === 'auto-sleep-minutes'}
        <MinutesControl {t} {inputId} settingId="auto_sleep_minutes" field="idle_minutes" />
    {:else if def.control.kind === 'auto-sleep-unread-minutes'}
        <MinutesControl {t} {inputId} settingId="auto_sleep_unread_minutes" field="unread_idle_minutes" />
    {:else if def.control.kind === 'config-toggle' || def.control.kind === 'crosstalk-card' || def.control.kind === 'auto-sleep' || def.control.kind === 'auto-sleep-unread'}
        <SwitchControl {def} {t} />
    {:else if def.control.kind === 'animations'}
        <MotionPanel {def} {t} />
    {:else if def.control.kind === 'toast-mode'}
        <div class="st-legacy"><ToastModePanel /></div>
    {:else if def.control.kind === 'screen-reader'}
        <div class="st-legacy"><ScreenReaderPanel /></div>
    {:else if def.control.kind === 'time-zone'}
        <TimeZonePanel {t} />
    {:else if def.control.kind === 'row-icons'}
        <RowIconsPanel {t} />
    {:else if def.control.kind === 'theme-picker'}
        <ThemePicker {t} />
    {:else if def.control.kind === 'foot-bar-layout'}
        <FootBarLayoutPanel half={def.control.half} {t} />
    {:else if def.control.kind === 'foot-bar-items'}
        <FootBarItemsPanel {t} />
    {:else if def.control.kind === 'config-bundle'}
        <ConfigBundlePanel {t} />
    {:else if def.control.kind === 'carnivore-account'}
        <AccountBody {t} />
    {:else if def.control.kind === 'web-push'}
        {#if inNativeShell()}
            <NativeAlertsPanel {t} />
        {:else}
            <WebPushPanel {t} />
        {/if}
    {:else if def.control.kind === 'install-report-privacy'}
        <InstallReportPrivacyPanel {t} />
    {:else if def.control.kind === 'agent-gate'}
        <AgentGatePanel {t} />
    {:else if def.control.kind === 'mcp-server'}
        <McpPanel {t} />
    {:else if def.control.kind === 'stats-collection'}
        <StatsCollectionPanel {t} part={def.control.part ?? 'all'} />
    {:else if def.control.kind === 'phone-link'}
        <PhoneLinkPanel {t} />
    {:else if def.control.kind === 'api-keys'}
        <ApiKeysPanel {t} />
    {:else if def.control.kind === 'tui-cli'}
        <TuiCliPanel {t} />
    {:else if def.control.kind === 'log-level'}
        <LogLevelPanel {t} />
    {:else if def.control.kind === 'app-update'}
        <AppUpdatePanel {t} />
    {:else if def.control.kind === 'mcp-tools'}
        <McpToolSwitchesPanel {t} />
    {:else if def.control.kind === 'beast-grid'}
        <BeastGridPanel {t} />
    {:else if def.control.kind === 'custom-domain-remove'}
        <CustomDomain {t} part="lifecycle" />
    {:else if def.control.kind === 'notify-destinations'}
        <DestinationsPanel {t} />
    {:else if def.control.kind === 'messaging'}
        <MessagingScreen {t} />
    {:else if def.control.kind === 'notify-link'}
        <LinkPanel {t} />
    {:else if def.control.kind === 'notify-matrix'}
        <MatrixPanel {t} />
    {:else if def.control.kind === 'notify-mutes'}
        <MutesPanel {t} />
    {:else if def.control.kind === 'notify-sync'}
        <SyncPanel {t} />
    {:else if def.control.kind === 'ai-connections'}
        <ConnectionsPanel {t} />
    {:else if def.control.kind === 'ai-routing'}
        <RoutingPanel {t} />
    {:else if def.control.kind === 'ai-calls'}
        <CallsPanel {t} />
    {:else if def.control.kind === 'pipeline-status'}
        <PipelineStatusPanel {t} />
    {:else if def.control.kind === 'deepsearch-scope'}
        <DeepSearchScopePanel {t} />
    {:else if def.control.kind === 'link'}
        <LinkControl action={def.control.action} {t} />
    {/if}
</SettingRow>
