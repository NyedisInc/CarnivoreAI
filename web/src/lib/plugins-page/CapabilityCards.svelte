
<script lang="ts">
    import Card from '../base/Card.svelte';
    import Checkbox from '../base/Checkbox.svelte';
    import Fold from '../base/Fold.svelte';
    import Tag from '../base/Tag.svelte';
    import {
        needsTick,
        type CplugEventsDecl,
        type CplugServicesDecl,
        type CplugUiSlotRow,
        type CplugWarning,
        type PermissionRow,
    } from './cplugs-adapter';
    import {
        formatWarnings,
        groupCapabilities,
        type CapabilityHost,
        type CapabilityTool,
    } from './install-sheet-model';
    import type { Translate } from '../sessions/types';

    interface Props {
        permissions: readonly PermissionRow[];
        uiSlots?: readonly CplugUiSlotRow[];
        services?: CplugServicesDecl | null;
        events?: CplugEventsDecl | null;
        warnings?: readonly (CplugWarning | string)[];
        tools?: readonly CapabilityTool[];
        networkHosts?: readonly CapabilityHost[];
        lanHosts?: readonly CapabilityHost[];
        ticks?: Record<string, boolean>;
        slotTicks?: Record<string, boolean>;
        busy?: boolean;
        onTick?: (name: string, checked: boolean) => void;
        onSlotTick?: (slot: string, checked: boolean) => void;
        t: Translate;
    }

    let {
        permissions,
        uiSlots = [],
        services = null,
        events = null,
        warnings = [],
        tools = [],
        networkHosts = [],
        lanHosts = [],
        ticks = $bindable({}),
        slotTicks = $bindable({}),
        busy = false,
        onTick,
        onSlotTick,
        t,
    }: Props = $props();

    let toolsOpen = $state(false);

    const grouped = $derived(groupCapabilities(permissions));
    const formattedWarnings = $derived(formatWarnings(warnings, t));
    const allHosts = $derived<CapabilityHost[]>([
        ...networkHosts.map((h) => ({ ...h, kind: 'network' as const })),
        ...lanHosts.map((h) => ({ ...h, kind: 'lan' as const })),
    ]);
    const serviceProvides = $derived(services?.provides ?? []);
    const serviceConsumes = $derived(services?.consumes ?? []);
    const eventsOn = $derived(events?.on ?? []);
    const eventsEmit = $derived(events?.emit ?? []);
    const hasServices = $derived(serviceProvides.length > 0 || serviceConsumes.length > 0);
    const hasEvents = $derived(eventsOn.length > 0 || eventsEmit.length > 0);
    const disclosureCount = $derived(
        tools.length +
            allHosts.length +
            serviceProvides.length +
            serviceConsumes.length +
            (eventsOn.length > 0 ? 1 : 0) +
            (eventsEmit.length > 0 ? 1 : 0),
    );

    function toggleTick(name: string, checked: boolean): void {
        ticks = { ...ticks, [name]: checked };
        onTick?.(name, checked);
    }

    function toggleSlotTick(slot: string, checked: boolean): void {
        slotTicks = { ...slotTicks, [slot]: checked };
        onSlotTick?.(slot, checked);
    }

    function schemaText(schema: unknown): string {
        try {
            return JSON.stringify(schema ?? {}, null, 2);
        } catch {
            return '{}';
        }
    }
</script>

{#if permissions.length > 0 || uiSlots.length > 0 || formattedWarnings.length > 0 || disclosureCount > 0}
<section class="pl-cap" data-capability-cards aria-label={t('plugins.page.install_sheet.cap_heading')}>
    {#each formattedWarnings as warning, i (`w:${i}`)}
        <p class="pl-cap__warn" role="alert" data-cap-warning>{warning}</p>
    {/each}

    {#if permissions.length > 0 || uiSlots.length > 0}
        {#if grouped.never.length > 0}
            <Card title={t('plugins.page.install_sheet.cap_never_title')} compact data-cap-group="never">
                {#snippet actions()}
                    <Tag tone="danger">{t('plugins.page.risk.never')}</Tag>
                {/snippet}
                <p class="pl-cap__blocked" role="alert" data-cap-never-blocked>
                    {t('plugins.page.install_sheet.cap_never_note')}
                </p>
                <ul class="pl-cap__list">
                    {#each grouped.never as perm, i (`n:${i}`)}
                        <li class="pl-cap__item" data-cap-perm={perm.name} data-risk="never">
                            <div class="pl-cap__item-head">
                                <span class="pl-cap__label">{perm.label}</span>
                                <Tag tone="danger">{t('plugins.page.risk.never')}</Tag>
                            </div>
                            <span class="pl-cap__name">{perm.name}</span>
                            <span class="pl-cap__reason">{perm.reason || t('plugins.page.sheet.no_reason')}</span>
                        </li>
                    {/each}
                </ul>
            </Card>
        {/if}

        {#if grouped.high.length > 0}
            <Card title={t('plugins.page.install_sheet.cap_high_title')} compact data-cap-group="high">
                {#snippet actions()}
                    <Tag tone="danger">{t('plugins.page.risk.high')}</Tag>
                {/snippet}
                <ul class="pl-cap__list">
                    {#each grouped.high as perm, i (`h:${i}`)}
                        <li class="pl-cap__item" data-cap-perm={perm.name} data-risk="high">
                            <div class="pl-cap__item-row">
                                {#if perm.granted}
                                    <Tag tone="ok">{t('plugins.page.install_sheet.cap_granted')}</Tag>
                                {:else}
                                    <Checkbox
                                        data-cap-tick={perm.name}
                                        aria-label={t('plugins.page.install_sheet.cap_tick_aria', { name: perm.label })}
                                        checked={ticks[perm.name] === true}
                                        disabled={busy}
                                        onchange={(e) => toggleTick(perm.name, e.currentTarget.checked)}
                                    />
                                {/if}
                                <div class="pl-cap__item-body">
                                    <div class="pl-cap__item-head">
                                        <span class="pl-cap__label">{perm.label}</span>
                                        <Tag tone="danger">{t('plugins.page.risk.high')}</Tag>
                                    </div>
                                    <span class="pl-cap__name">{perm.name}</span>
                                    <span class="pl-cap__reason" data-cap-reason>
                                        {perm.reason || t('plugins.page.sheet.no_reason')}
                                    </span>
                                </div>
                            </div>
                        </li>
                    {/each}
                </ul>
            </Card>
        {/if}

        {#if grouped.medium.length > 0}
            <Card title={t('plugins.page.install_sheet.cap_medium_title')} compact data-cap-group="medium">
                {#snippet actions()}
                    <Tag tone="warn">{t('plugins.page.risk.medium')}</Tag>
                {/snippet}
                <ul class="pl-cap__list">
                    {#each grouped.medium as perm, i (`m:${i}`)}
                        <li class="pl-cap__item" data-cap-perm={perm.name} data-risk="medium">
                            <div class="pl-cap__item-row">
                                {#if perm.granted}
                                    <Tag tone="ok">{t('plugins.page.install_sheet.cap_granted')}</Tag>
                                {:else}
                                    <Checkbox
                                        data-cap-tick={perm.name}
                                        aria-label={t('plugins.page.install_sheet.cap_tick_aria', { name: perm.label })}
                                        checked={ticks[perm.name] === true}
                                        disabled={busy}
                                        onchange={(e) => toggleTick(perm.name, e.currentTarget.checked)}
                                    />
                                {/if}
                                <div class="pl-cap__item-body">
                                    <div class="pl-cap__item-head">
                                        <span class="pl-cap__label">{perm.label}</span>
                                        <Tag tone="warn">{t('plugins.page.risk.medium')}</Tag>
                                    </div>
                                    <span class="pl-cap__name">{perm.name}</span>
                                    <span class="pl-cap__reason" data-cap-reason>
                                        {perm.reason || t('plugins.page.sheet.no_reason')}
                                    </span>
                                </div>
                            </div>
                        </li>
                    {/each}
                </ul>
            </Card>
        {/if}

        {#if grouped.low.length > 0}
            <Card title={t('plugins.page.install_sheet.cap_low_title')} compact data-cap-group="low">
                {#snippet actions()}
                    <Tag tone="ok">{t('plugins.page.install_sheet.cap_low_tag')}</Tag>
                {/snippet}
                <p class="pl-cap__summary" data-cap-low-summary>
                    {t('plugins.page.install_sheet.cap_low_summary', { count: grouped.low.length })}
                </p>
                <ul class="pl-cap__list">
                    {#each grouped.low as perm, i (`l:${i}`)}
                        <li class="pl-cap__item" data-cap-perm={perm.name} data-risk="low">
                            <div class="pl-cap__item-head">
                                <span class="pl-cap__label">{perm.label}</span>
                                <Tag tone="ok">{t('plugins.page.risk.low')}</Tag>
                            </div>
                            <span class="pl-cap__name">{perm.name}</span>
                            {#if perm.reason}<span class="pl-cap__reason" data-cap-reason>{perm.reason}</span>{/if}
                        </li>
                    {/each}
                </ul>
            </Card>
        {/if}

        {#if uiSlots.length > 0}
            <Card title={t('plugins.page.install_sheet.cap_ui_slots_title')} compact data-cap-group="ui_slots">
                {#snippet actions()}
                    <Tag tone="warn">{t('plugins.page.risk.medium')}</Tag>
                {/snippet}
                <ul class="pl-cap__list">
                    {#each uiSlots as slot, i (`slot:${slot.slot}:${i}`)}
                        <li class="pl-cap__item" data-cap-slot={slot.slot} data-risk={slot.risk}>
                            <div class="pl-cap__item-row">
                                {#if slot.granted}
                                    <Tag tone="ok">{t('plugins.page.install_sheet.cap_granted')}</Tag>
                                {:else if slot.needs_tick || needsTick(slot.risk)}
                                    <Checkbox
                                        data-cap-slot-tick={slot.slot}
                                        aria-label={t('plugins.page.install_sheet.cap_slot_tick_aria', { slot: slot.slot })}
                                        checked={slotTicks[slot.slot] === true}
                                        disabled={busy}
                                        onchange={(e) => toggleSlotTick(slot.slot, e.currentTarget.checked)}
                                    />
                                {/if}
                                <div class="pl-cap__item-body">
                                    <div class="pl-cap__item-head">
                                        <span class="pl-cap__label">
                                            {t('plugins.page.install_sheet.ui_slot_label', { slot: slot.slot, count: slot.count })}
                                        </span>
                                        <Tag
                                            tone={slot.risk === 'high' || slot.risk === 'never'
                                                ? 'danger'
                                                : slot.risk === 'low'
                                                  ? 'ok'
                                                  : 'warn'}
                                        >
                                            {t(`plugins.page.risk.${slot.risk}`)}
                                        </Tag>
                                    </div>
                                    <span class="pl-cap__name">{`ui.slot:${slot.slot}`}</span>
                                    <span class="pl-cap__reason" data-cap-slot-reason>
                                        {slot.reason || t('plugins.page.sheet.no_reason')}
                                    </span>
                                </div>
                            </div>
                        </li>
                    {/each}
                </ul>
            </Card>
        {/if}
    {/if}

    {#if disclosureCount > 0}
    <Fold label={t('plugins.page.install_sheet.tools_hosts_fold')} count={disclosureCount} bind:open={toolsOpen}>
        <div class="pl-cap__disclosure" data-cap-tools-hosts>
            {#if tools.length > 0}
                    <p class="pl-cap__subhead">{t('plugins.page.install_sheet.tools_heading')}</p>
                    <ul class="pl-cap__list">
                        {#each tools as tool, i (`t:${i}`)}
                            <li class="pl-cap__item" data-cap-tool={tool.name}>
                                <div class="pl-cap__item-head">
                                    <span class="pl-cap__label">{tool.name}</span>
                                    {#if tool.gate}<Tag tone="neutral">{tool.gate}</Tag>{/if}
                                </div>
                                {#if tool.description}<p class="pl-cap__desc">{tool.description}</p>{/if}
                                {#if tool.input_schema !== undefined}
                                    <pre class="pl-cap__schema">{schemaText(tool.input_schema)}</pre>
                                {/if}
                            </li>
                        {/each}
                    </ul>
                {/if}
                {#if allHosts.length > 0}
                    <p class="pl-cap__subhead">{t('plugins.page.install_sheet.hosts_heading')}</p>
                    <ul class="pl-cap__list">
                        {#each allHosts as host, i (`host:${i}`)}
                            <li class="pl-cap__item" data-cap-host={host.host}>
                                <div class="pl-cap__item-head">
                                    <span class="pl-cap__label">{host.host}</span>
                                    {#if host.methods?.length}
                                        <Tag tone="info">{host.methods.join(' ')}</Tag>
                                    {/if}
                                </div>
                                {#if host.paths?.length}<span class="pl-cap__name">{host.paths.join(', ')}</span>{/if}
                                {#if host.reason}<span class="pl-cap__reason">{host.reason}</span>{/if}
                            </li>
                        {/each}
                    </ul>
                {/if}
                {#if hasServices}
                    <p class="pl-cap__subhead">{t('plugins.page.install_sheet.services_heading')}</p>
                    <ul class="pl-cap__list" data-cap-services>
                        {#each serviceProvides as svc, i (`sp:${svc.name}:${i}`)}
                            <li class="pl-cap__item" data-cap-service-provides={svc.name}>
                                <span class="pl-cap__label">
                                    {t('plugins.page.install_sheet.service_provides', {
                                        name: svc.name,
                                        methods: svc.methods.join(', '),
                                    })}
                                </span>
                            </li>
                        {/each}
                        {#each serviceConsumes as svcName, i (`sc:${svcName}:${i}`)}
                            <li class="pl-cap__item" data-cap-service-consumes={svcName}>
                                <span class="pl-cap__label">
                                    {t('plugins.page.install_sheet.service_consumes', { name: svcName })}
                                </span>
                            </li>
                        {/each}
                    </ul>
                {/if}
                {#if hasEvents}
                    <p class="pl-cap__subhead">{t('plugins.page.install_sheet.events_heading')}</p>
                    <ul class="pl-cap__list" data-cap-events>
                        {#if eventsOn.length > 0}
                            <li class="pl-cap__item" data-cap-events-on>
                                <span class="pl-cap__label">
                                    {t('plugins.page.install_sheet.events_on', { names: eventsOn.join(', ') })}
                                </span>
                            </li>
                        {/if}
                        {#if eventsEmit.length > 0}
                            <li class="pl-cap__item" data-cap-events-emit>
                                <span class="pl-cap__label">
                                    {t('plugins.page.install_sheet.events_emit', { names: eventsEmit.join(', ') })}
                                </span>
                            </li>
                        {/if}
                    </ul>
                {/if}
        </div>
    </Fold>
    {/if}
</section>
{/if}

<style>
    @layer components {
        .pl-cap {
            display: flex;
            flex-direction: column;
            gap: var(--oc-space-2);
        }

        .pl-cap__warn {
            margin: 0;
            padding: var(--oc-space-1-5) var(--oc-space-2);
            border-left: var(--oc-border) solid var(--oc-coral);
            background: color-mix(in srgb, var(--oc-coral) 12%, var(--oc-ground-field));
            color: var(--oc-text-primary);
            font-size: var(--oc-fs-body);
            line-height: var(--oc-lh-body);
            overflow-wrap: anywhere;
        }

        .pl-cap__blocked {
            margin: 0;
            color: var(--oc-coral);
            font-size: var(--oc-fs-label);
            line-height: var(--oc-lh-body);
        }

        .pl-cap__summary,
        .pl-cap__empty {
            margin: 0;
            color: var(--oc-text-secondary);
            font-size: var(--oc-fs-label);
            line-height: var(--oc-lh-body);
        }

        .pl-cap__list {
            display: flex;
            flex-direction: column;
            gap: var(--oc-space-1-5);
            margin: 0;
            padding: 0;
            list-style: none;
        }

        .pl-cap__item {
            display: flex;
            flex-direction: column;
            gap: var(--oc-space-0-5);
            padding-top: var(--oc-space-1);
            border-top: var(--oc-border) solid var(--oc-line-faint);
        }

        .pl-cap__item:first-child {
            padding-top: 0;
            border-top: 0;
        }

        .pl-cap__item-row {
            display: flex;
            align-items: flex-start;
            gap: var(--oc-space-2);
        }

        .pl-cap__item-body {
            display: flex;
            flex: 1 1 auto;
            flex-direction: column;
            gap: var(--oc-space-0-5);
            min-width: 0;
        }

        .pl-cap__item-head {
            display: flex;
            flex-wrap: wrap;
            align-items: center;
            justify-content: space-between;
            gap: var(--oc-space-1);
        }

        .pl-cap__label {
            color: var(--oc-text-primary);
            font-size: var(--oc-fs-body);
            overflow-wrap: anywhere;
        }

        .pl-cap__name,
        .pl-cap__reason {
            color: var(--oc-text-dim);
            font-size: var(--oc-fs-micro);
            overflow-wrap: anywhere;
        }

        .pl-cap__reason {
            color: var(--oc-text-secondary);
            font-size: var(--oc-fs-label);
        }

        .pl-cap__disclosure {
            display: flex;
            flex-direction: column;
            gap: var(--oc-space-2);
        }

        .pl-cap__subhead {
            margin: 0;
            color: var(--oc-text-muted);
            font-size: var(--oc-fs-micro);
            letter-spacing: var(--oc-tracking-caps);
            text-transform: uppercase;
        }

        .pl-cap__desc {
            margin: 0;
            color: var(--oc-text-secondary);
            font-size: var(--oc-fs-label);
            white-space: pre-wrap;
            overflow-wrap: anywhere;
        }

        .pl-cap__schema {
            margin: 0;
            padding: var(--oc-space-1);
            border: var(--oc-border) solid var(--oc-line-faint);
            border-radius: var(--oc-radius-control);
            background: var(--oc-surface-sunken);
            color: var(--oc-text-muted);
            font-family: var(--oc-font);
            font-size: var(--oc-fs-micro);
            line-height: var(--oc-lh-body);
            overflow-x: auto;
        }
    }
</style>
