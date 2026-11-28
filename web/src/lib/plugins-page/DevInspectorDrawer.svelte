
<script lang="ts">
    import { IconButton, Tag } from '../base';
    import { t as appT } from '../i18n/index.svelte';
    import { pluginsStore, type PluginInspectorSnapshot } from '../plugins/store.svelte';
    import type { Translate } from '../sessions/types';
    import Sheet from '../sheet/Sheet.svelte';
    import type { CplugItem } from './cplugs-adapter';
    import {
        deriveDevLeaseSummary,
        inspectorStatusInfo,
        type InspectorTabId,
    } from './dev-inspector';
    import InspectorPanels from './InspectorPanels.svelte';
    import './dev-inspector.css';

    interface Props {
        open: boolean;
        cplugId: string | null;
        plugin?: CplugItem | null;
        snapshot?: PluginInspectorSnapshot | null;
        useStore?: boolean;
        initialTab?: InspectorTabId;
        busy?: boolean;
        onClose: () => void;
        onRestart?: (cplugId: string) => Promise<unknown>;
        onPauseToggle?: (cplugId: string, paused: boolean) => Promise<unknown>;
        t?: Translate;
    }

    const {
        open,
        cplugId,
        plugin = null,
        snapshot,
        useStore = snapshot === undefined,
        initialTab = 'trace',
        busy = false,
        onClose,
        onRestart = (id) => pluginsStore.restartPlugin(id),
        onPauseToggle = (id, paused) => (paused ? pluginsStore.pausePlugin(id) : pluginsStore.resumePlugin(id)),
        t = appT,
    }: Props = $props();

    $effect(() => {
        if (!open || !cplugId || !useStore) return;
        return pluginsStore.acquireInspector(cplugId, plugin?.installKey ?? null);
    });

    $effect(() => {
        if (!open || typeof window === 'undefined') return;
        const onKeydown = (event: KeyboardEvent): void => {
            if (event.key !== 'Escape' || event.defaultPrevented) return;
            event.preventDefault();
            event.stopPropagation();
            onClose();
        };
        window.addEventListener('keydown', onKeydown, { capture: true });
        return () => window.removeEventListener('keydown', onKeydown, { capture: true });
    });

    const activeSnapshot = $derived(
        snapshot !== undefined ? snapshot : cplugId ? pluginsStore.inspectorOf(cplugId) : null,
    );
    const subjectId = $derived(plugin?.cplugId ?? activeSnapshot?.cplug_id ?? cplugId ?? '');
    const displayName = $derived(plugin?.name || activeSnapshot?.cplug_id || cplugId || '');
    const statusInfo = $derived(inspectorStatusInfo(plugin, activeSnapshot));
    const leaseSummary = $derived(deriveDevLeaseSummary(activeSnapshot, plugin, t));
    const trustBadge = $derived(plugin?.trustBadge || activeSnapshot?.trust_badge || null);
    const isUnverified = $derived(Boolean(plugin?.unverified || activeSnapshot?.unverified));
</script>

{#if open && subjectId}
    <Sheet
        place="float"
        width="var(--oc-sheet-w-wide)"
        class="pl-inspector"
        aria-label={t('plugins.page.inspector.label', { name: displayName })}
        data-dev-inspector={subjectId}
    >
        <header class="pl-inspector__head">
            <div class="pl-inspector__head-main">
                <span class="pl-inspector__kicker">{t('plugins.page.inspector.kicker')}</span>
                <h2 class="pl-inspector__title" data-inspector-title>{displayName}</h2>
                <div class="pl-inspector__badges">
                    <Tag tone={statusInfo.tone} data-inspector-status>{t(statusInfo.key)}</Tag>
                    {#if trustBadge}
                        <Tag tone={isUnverified ? 'warn' : 'neutral'} data-inspector-trust>{trustBadge}</Tag>
                    {/if}
                    {#if leaseSummary.active}
                        <Tag tone="info" data-inspector-lease-badge>{t('plugins.page.inspector.dev_lease.active')}</Tag>
                    {/if}
                </div>
            </div>
            <div class="pl-inspector__head-actions">
                <IconButton
                    label={t('plugins.page.inspector.close')}
                    variant="close"
                    icon="close"
                    iconSize={14}
                    data-inspector-close
                    onclick={onClose}
                />
            </div>
        </header>

        <InspectorPanels
            {subjectId}
            {plugin}
            snapshot={activeSnapshot}
            loading={useStore && pluginsStore.loading}
            {initialTab}
            {busy}
            {onRestart}
            {onPauseToggle}
            {t}
        />
    </Sheet>
{/if}
