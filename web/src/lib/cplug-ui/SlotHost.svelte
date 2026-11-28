
<script lang="ts">
    import { Button, Tag } from '../base';
    import { buttonAttrs } from '../base/classes';
    import Icon from '../../opscenter/ui/Icon.svelte';
    import { icons } from '../../opscenter/ui/icons';
    import { t as reactiveT } from '../i18n/index.svelte';
    import { pluginsStore, type SlotContribution, type StoreCplugRow } from '../plugins/store.svelte';
    import type { Translate } from '../sessions/types';
    import { errorCode } from './api';
    import './cplug-ui.css';
    import Renderer from './Renderer.svelte';
    import {
        canonicalSlot,
        executeSlotAction,
        sortSlotEntries,
        validateSlotEntry,
        type SlotAction,
        type SlotDeclared,
        type ValidSlotEntry,
    } from './slots';
    import type { Action } from './validate';

    interface Props {
        slot: string;
        items?: readonly SlotContribution[];
        plugins?: readonly StoreCplugRow[];
        sessionRef?: string | null;
        layout?: 'column' | 'row';
        compact?: boolean;
        empty?: string | null;
        t?: Translate;
        run?: (entry: ValidSlotEntry, action: SlotAction) => Promise<unknown>;
        onAction?: (entry: ValidSlotEntry, result: unknown) => void;
    }

    const {
        slot,
        items,
        plugins,
        sessionRef = null,
        layout = 'column',
        compact = false,
        empty = null,
        t = reactiveT,
        run,
        onAction,
    }: Props = $props();

    let confirmKey = $state<string | null>(null);
    let busyKey = $state<string | null>(null);
    let errors = $state<Record<string, string>>({});

    $effect(() => {
        if (items !== undefined) return;
        return pluginsStore.acquire({ includeSlots: true });
    });

    const slotName = $derived(canonicalSlot(slot));
    const rawItems = $derived(items ?? pluginsStore.slotsFor(slotName));

    function rowFor(pluginId: string): StoreCplugRow | undefined {
        return plugins?.find((r) => r.id === pluginId) ?? pluginsStore.rowOf(pluginId);
    }

    function declaredFor(row: StoreCplugRow | undefined): SlotDeclared {
        return {
            routes: row?.routes ?? [],
            tools: row?.declared_tools ?? [],
        };
    }

    function pluginNameOf(pluginId: string, row: StoreCplugRow | undefined): string {
        if (row?.name) return row.name;
        if (row?.name_key) return t(row.name_key);
        return pluginId;
    }

    const validatedEntries = $derived.by(() => {
        const valid: ValidSlotEntry[] = [];
        for (const entry of rawItems) {
            const parsed = validateSlotEntry(entry, declaredFor(rowFor(entry.plugin_id)));
            if (parsed) valid.push(parsed);
        }
        return sortSlotEntries(valid);
    });

    const OFFLINE_CODES = new Set(['cplug_not_running', 'cplug_disabled', 'cplug_paused']);

    function failureMessage(error: unknown): string {
        const code = errorCode(error);
        if (code && OFFLINE_CODES.has(code)) return t('cplug_ui.not_running');
        return t('cplug_ui.action_failed');
    }

    async function runSlotAction(entry: ValidSlotEntry, action: SlotAction): Promise<unknown> {
        if (run) return run(entry, action);
        return executeSlotAction(entry.entry.plugin_id, action, { sessionRef });
    }

    async function runDocumentAction(entry: ValidSlotEntry, action: Action): Promise<void> {
        const mapped: SlotAction =
            action.call === 'tool'
                ? { kind: 'tool', tool: action.name, ...(action.payload ? { payload: action.payload } : {}) }
                : { kind: 'route', route: action.route, ...(action.payload ? { payload: action.payload } : {}) };
        const result = await runSlotAction(entry, mapped);
        onAction?.(entry, result);
    }

    function requestDescriptor(entry: Extract<ValidSlotEntry, { kind: 'descriptor' }>, key: string): void {
        if (!entry.action || entry.disabled || busyKey === key) return;
        if (entry.confirm && confirmKey !== key) {
            confirmKey = key;
            return;
        }
        void triggerDescriptor(entry, key);
    }

    async function triggerDescriptor(entry: Extract<ValidSlotEntry, { kind: 'descriptor' }>, key: string): Promise<void> {
        if (!entry.action || entry.disabled || busyKey === key) return;
        confirmKey = null;
        busyKey = key;
        if (errors[key]) {
            const { [key]: _cleared, ...rest } = errors;
            errors = rest;
        }
        try {
            const result = await runSlotAction(entry, entry.action);
            onAction?.(entry, result);
        } catch (error) {
            errors = { ...errors, [key]: failureMessage(error) };
        } finally {
            busyKey = null;
        }
    }

    function tagToneOf(tone: ValidSlotEntry extends never ? never : string | null): 'neutral' | 'accent' | 'warn' | 'danger' {
        if (tone === 'danger') return 'danger';
        if (tone === 'warn') return 'warn';
        if (tone === 'accent') return 'accent';
        return 'neutral';
    }
</script>

{#if validatedEntries.length > 0 || empty !== null}
    <section
        class="cu-slot"
        class:cu-slot--row={layout === 'row'}
        data-cu-slot={slotName}
        aria-label={t('cplug_ui.slot.region', { slot: slotName })}
    >
        {#each validatedEntries as entry, idx (`${entry.entry.plugin_id}:${entry.entry.install_key}:${entry.id}:${idx}`)}
            {@const key = `${entry.entry.plugin_id}:${entry.entry.install_key}:${entry.id}:${idx}`}
            {@const row = rowFor(entry.entry.plugin_id)}
            {@const pluginName = pluginNameOf(entry.entry.plugin_id, row)}
            {@const unverified = row?.unverified === true}
            {#if entry.kind === 'document'}
                <div class="cu-slot__item" data-cu-slot-item={entry.id} data-plugin-id={entry.entry.plugin_id}>
                    <Renderer
                        cplugId={entry.entry.plugin_id}
                        name={pluginName}
                        {unverified}
                        document={entry.document}
                        declared={{ routes: row?.routes ?? [], tools: row?.declared_tools ?? [] }}
                        {t}
                        run={(action) => runDocumentAction(entry, action)}
                    />
                </div>
            {:else}
                <div class="cu-slot__item" data-cu-slot-item={entry.id} data-plugin-id={entry.entry.plugin_id}>
                    <div class="cu-slot__head">
                        {#if entry.icon && entry.icon in icons}
                            <Icon name={entry.icon} size={14} />
                        {/if}
                        {#if entry.action?.kind === 'href'}
                            {#if entry.action.external && !entry.disabled}
                                <a
                                    {...buttonAttrs(entry.tone === 'danger' ? 'danger' : 'secondary', compact ? 'sm' : 'md')}
                                    href={entry.action.href}
                                    target="_blank"
                                    rel="noopener noreferrer"
                                    title={entry.tooltip ?? undefined}
                                    data-cu-slot-link={entry.id}
                                >
                                    {entry.label}
                                </a>
                            {:else}
                                <Button
                                    variant={entry.tone === 'danger' ? 'danger' : 'secondary'}
                                    size={compact ? 'sm' : 'md'}
                                    href={entry.action.href}
                                    disabled={entry.disabled}
                                    title={entry.tooltip ?? undefined}
                                    data-cu-slot-link={entry.id}
                                >
                                    {entry.label}
                                </Button>
                            {/if}
                        {:else if entry.action !== null}
                            {#if confirmKey === key && entry.confirm}
                                <span class="cu-action__ask" data-cu-slot-confirm-text>{entry.confirm}</span>
                                <Button
                                    variant={entry.tone === 'danger' ? 'danger' : 'confirm'}
                                    size={compact ? 'sm' : 'md'}
                                    disabled={busyKey === key}
                                    data-cu-slot-confirm-yes
                                    onclick={() => void triggerDescriptor(entry, key)}
                                >
                                    {t('cplug_ui.confirm_yes')}
                                </Button>
                                <Button
                                    size={compact ? 'sm' : 'md'}
                                    data-cu-slot-confirm-no
                                    onclick={() => (confirmKey = null)}
                                >
                                    {t('cplug_ui.confirm_no')}
                                </Button>
                            {:else}
                                <Button
                                    variant={entry.tone === 'danger' ? 'danger' : 'secondary'}
                                    size={compact ? 'sm' : 'md'}
                                    disabled={entry.disabled || busyKey === key}
                                    title={entry.tooltip ?? undefined}
                                    data-cu-slot-action={entry.id}
                                    onclick={() => requestDescriptor(entry, key)}
                                >
                                    {entry.label}
                                </Button>
                            {/if}
                        {:else}
                            <span class="cu-slot__label">{entry.label}</span>
                        {/if}

                        {#if entry.badge}
                            <Tag tone={tagToneOf(entry.tone)} data-cu-slot-badge>{entry.badge}</Tag>
                        {/if}
                        <Tag tone={unverified ? 'warn' : 'neutral'} data-cu-slot-plugin={entry.entry.plugin_id}>
                            {pluginName}
                        </Tag>
                        {#if unverified}
                            <Tag tone="warn" data-cu-slot-unverified>{t('cplug_ui.mark.unverified')}</Tag>
                        {/if}
                    </div>
                    {#if entry.subtitle}
                        <p class="cu-slot__desc">{entry.subtitle}</p>
                    {/if}
                    {#if entry.description}
                        <p class="cu-slot__desc">{entry.description}</p>
                    {/if}
                    {#if errors[key]}
                        <p class="cu-slot__error" role="status" data-cu-slot-error>{errors[key]}</p>
                    {/if}
                </div>
            {/if}
        {:else}
            {#if empty !== null}
                <p class="cu-slot__empty" data-cu-slot-empty>{empty || t('cplug_ui.nothing_here')}</p>
            {/if}
        {/each}
    </section>
{/if}
