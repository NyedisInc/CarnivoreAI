<script lang="ts">
    import { Fold, State, Tag } from '../base';
    import { t as appT } from '../i18n/index.svelte';
    import type { PluginInspectorSnapshot } from '../plugins/store.svelte';
    import InspectorPanels from '../plugins-page/InspectorPanels.svelte';
    import type { Translate } from '../sessions/types';
    import type { DevStreamRecord } from './studio-store.svelte';
    import type { StudioInspectorSnapshot } from './types';
    import './plugin-studio.css';

    interface Props {
        pluginId: string;
        studioInspector: StudioInspectorSnapshot | null;
        liveInspector: PluginInspectorSnapshot | null;
        devEvents: DevStreamRecord[];
        loading?: boolean;
        t?: Translate;
    }

    const {
        pluginId,
        studioInspector,
        liveInspector,
        devEvents,
        loading = false,
        t = appT,
    }: Props = $props();

    const effectiveSnapshot = $derived<PluginInspectorSnapshot | null>(liveInspector ?? studioInspector);
    const caps = $derived(studioInspector?.capabilities ?? null);
    const uiErrors = $derived(studioInspector?.ui_errors ?? []);
    const slotRenderEntries = $derived.by(() => {
        const raw = studioInspector?.slot_renders;
        if (!raw) return [] as Array<{ slot: string; items: Array<Record<string, unknown>> }>;
        if (Array.isArray(raw)) {
            return raw.length > 0 ? [{ slot: 'default', items: raw }] : [];
        }
        return Object.entries(raw)
            .filter(([, items]) => Array.isArray(items) && items.length > 0)
            .map(([slot, items]) => ({ slot, items }));
    });
    const slotRenderCount = $derived(
        slotRenderEntries.reduce((sum, entry) => sum + entry.items.length, 0),
    );
</script>

<div class="ps-right-body" data-studio-inspector>
    {#if caps}
        <Fold label={t('plugin_studio.inspector.capabilities_heading')} open={true}>
            <dl class="ps-kv-grid">
                <dt class="ps-kv-grid__key">{t('plugin_studio.inspector.permissions')}</dt>
                <dd class="ps-kv-grid__val">
                    {caps.permissions.length ? caps.permissions.join(', ') : t('plugin_studio.inspector.none')}
                </dd>

                <dt class="ps-kv-grid__key">{t('plugin_studio.inspector.tools')}</dt>
                <dd class="ps-kv-grid__val">
                    {caps.tools.length ? caps.tools.join(', ') : t('plugin_studio.inspector.none')}
                </dd>

                <dt class="ps-kv-grid__key">{t('plugin_studio.inspector.routes')}</dt>
                <dd class="ps-kv-grid__val">
                    {caps.routes.length ? caps.routes.join(', ') : t('plugin_studio.inspector.none')}
                </dd>

                <dt class="ps-kv-grid__key">{t('plugin_studio.inspector.views')}</dt>
                <dd class="ps-kv-grid__val">
                    {caps.views.length ? caps.views.join(', ') : t('plugin_studio.inspector.none')}
                </dd>

                <dt class="ps-kv-grid__key">{t('plugin_studio.inspector.ui_slots')}</dt>
                <dd class="ps-kv-grid__val">
                    {caps.ui_slots.length ? caps.ui_slots.join(', ') : t('plugin_studio.inspector.none')}
                </dd>

                <dt class="ps-kv-grid__key">{t('plugin_studio.inspector.services_provides')}</dt>
                <dd class="ps-kv-grid__val">
                    {caps.services_provides.length ? caps.services_provides.join(', ') : t('plugin_studio.inspector.none')}
                </dd>

                <dt class="ps-kv-grid__key">{t('plugin_studio.inspector.events_emit')}</dt>
                <dd class="ps-kv-grid__val">
                    {caps.events_emit.length ? caps.events_emit.join(', ') : t('plugin_studio.inspector.none')}
                </dd>
            </dl>
        </Fold>
    {/if}

    {#if uiErrors.length > 0}
        <Fold label={`${t('plugin_studio.inspector.ui_errors')} (${uiErrors.length})`} open={true}>
            <div class="ps-check-list">
                {#each uiErrors as item, idx (`ui-err-${idx}`)}
                    <div class="ps-check-row">
                        <div class="ps-check-row__top">
                            <span class="ps-check-row__label">{String(item.code ?? 'error')}</span>
                            <Tag tone="danger">{t('plugin_studio.readiness.status.fail')}</Tag>
                        </div>
                        {#if item.detail}
                            <p class="ps-check-row__detail">{String(item.detail)}</p>
                        {/if}
                    </div>
                {/each}
            </div>
        </Fold>
    {/if}

    {#if slotRenderEntries.length > 0}
        <Fold label={`${t('plugin_studio.inspector.slot_renders')} (${slotRenderCount})`} open={true}>
            <div class="ps-check-list" data-studio-slot-renders>
                {#each slotRenderEntries as entry (entry.slot)}
                    <div class="ps-check-row">
                        <div class="ps-check-row__top">
                            <span class="ps-check-row__label">{entry.slot}</span>
                            <Tag tone="info">{entry.items.length}</Tag>
                        </div>
                        <pre class="ps-pre">{JSON.stringify(entry.items, null, 2)}</pre>
                    </div>
                {/each}
            </div>
        </Fold>
    {/if}

    {#if devEvents.length > 0}
        <Fold label={`${t('plugin_studio.inspector.events')} (${devEvents.length})`}>
            <pre class="ps-pre">{JSON.stringify(devEvents, null, 2)}</pre>
        </Fold>
    {/if}

    {#if effectiveSnapshot}
        <InspectorPanels
            subjectId={pluginId}
            snapshot={effectiveSnapshot}
            {loading}
            showControls={false}
            {t}
        />
    {:else if !loading}
        <State kind="empty" title={t('plugin_studio.inspector.heading')} />
    {/if}
</div>
