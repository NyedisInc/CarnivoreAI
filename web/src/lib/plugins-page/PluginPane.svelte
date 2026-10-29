
<script lang="ts">
    import { SKILL_KEYS } from '../../../../client/js/labels/skill.js';
    import { Button } from '../base';
    import Tabs, { panelAttrs } from '../../opscenter/ui/Tabs.svelte';
    import type { Translate } from '../sessions/types';
    import ActivityLog from './ActivityLog.svelte';
    import type { ActivityRow, CplugItem } from './cplugs-adapter';
    import DisableConfirm from './DisableConfirm.svelte';
    import PermissionSheet from './PermissionSheet.svelte';
    import PluginData from './PluginData.svelte';
    import PluginOverview from './PluginOverview.svelte';
    import PluginSettings from './PluginSettings.svelte';
    import { paneReason, paneTabs, type PaneTab, type PurgePrice } from './plugin-pane';
    import './plugin-pane.css';

    interface Props {
        plugin: CplugItem;
        tab: PaneTab;
        onTab: (id: PaneTab) => void;
        asking?: boolean;
        busy?: boolean;
        error?: string | null;
        onConfirmOff: () => void;
        onCancelOff: () => void;
        onGrant: (ticks: string[]) => void;
        sheetStamp?: string;
        loadActivity: (cplugId: string) => Promise<ActivityRow[]>;
        purge?: (cplugId: string, confirmToken?: string) => Promise<PurgePrice>;
        onPurged?: () => void;
        onUninstall?: () => void;
        uninstalling?: boolean;
        uninstallError?: string | null;
        t: Translate;
    }

    const { plugin, tab, onTab, asking = false, busy = false, error = null, onConfirmOff, onCancelOff, onGrant, sheetStamp = '', loadActivity, purge, onPurged, onUninstall, uninstalling = false, uninstallError = null, t }: Props = $props();

    const reason = $derived(paneReason(plugin, t));
    const tabs = $derived(paneTabs(plugin, t));
    const idBase = $derived(`plugin-pane-${plugin.cplugId}`);
</script>

<div class="plp" data-plugin-pane={plugin.cplugId}>
    {#if reason}
        <div class="plp__why" data-plugin-reason={reason.kind}>
            <p class="plp__why-text">{reason.lead} <span class="plp__why-more">{reason.more}</span></p>
            {#if reason.kind === 'grant'}
                <Button variant="confirm" data-plugin-review onclick={() => onTab('permissions')}>{t('plugins.page.pane.review')}</Button>
            {/if}
        </div>
    {/if}
    {#if error}<p class="plp__error" role="alert" data-plugin-pane-error>{error}</p>{/if}
    {#if asking}
        <DisableConfirm name={plugin.name} dependents={plugin.deps.enabledDependents} {busy} onConfirm={onConfirmOff} onCancel={onCancelOff} {t} />
    {/if}
    <Tabs class="plp-tabs" {tabs} active={tab} onSelect={(id) => onTab(id as PaneTab)} label={t('plugins.page.pane.tabs', { name: plugin.name })} {idBase} />
    <div class="plp__panel" {...panelAttrs(idBase, tab)} data-plugin-panel={tab}>
        {#key plugin.id}
            {#if tab === 'overview'}
                <PluginOverview {plugin} {t} />
            {:else if tab === 'settings'}
                <PluginSettings {plugin} {t} />
            {:else if tab === 'permissions'}
                {#key sheetStamp}
                    <PermissionSheet
                        rows={plugin.permissions}
                        missing={plugin.missing}
                        waiting={plugin.state === 'needs_approval'}
                        off={plugin.state === 'disabled'}
                        consent={plugin.consentRequired}
                        warnings={plugin.warnings}
                        {busy}
                        {onGrant}
                        {t}
                    />
                {/key}
                {#if plugin.state !== 'removed'}<ActivityLog load={() => loadActivity(plugin.cplugId)} {t} />{/if}
            {:else}
                <PluginData {plugin} {purge} {onPurged} {t} />
            {/if}
        {/key}
        {#if onUninstall}
            <div class="plp-region" data-plugin-uninstall>
                {#if uninstallError}<p class="plp__error" role="alert" data-plugin-uninstall-error>{uninstallError}</p>{/if}
                <div class="plp-actions">
                    <Button variant="danger" data-act="uninstall" disabled={uninstalling} onclick={onUninstall}
                        >{uninstalling ? t(SKILL_KEYS.uninstallWorking) : t(SKILL_KEYS.actionUninstall)}</Button
                    >
                </div>
            </div>
        {/if}
    </div>
</div>
