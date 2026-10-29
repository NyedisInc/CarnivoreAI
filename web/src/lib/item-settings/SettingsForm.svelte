
<script lang="ts">
    import { untrack } from 'svelte';
    import type { Translate } from '../sessions/types';
    import Switch from '../base/Switch.svelte';
    import Button from '../base/Button.svelte';
    import Segmented from '../base/Segmented.svelte';
    import Select from '../base/Select.svelte';
    import type { WidgetSettingField, WidgetSettingsSchema } from '../../opscenter/widgets/types';
    import { fieldDisabled, resolveValue, type SettingValue } from './api';
    import { controlOf, settingGroups } from './schema-layout';
    import SettingsMatrix from './SettingsMatrix.svelte';

    interface Props {
        schema: WidgetSettingsSchema;
        values: Readonly<Record<string, SettingValue>>;
        t: Translate;
        onChange: (key: string, value: SettingValue | null) => void;
        busyKey?: string | null;
        error?: { key: string; text: string } | null;
        warnings?: readonly { field?: string; message: string; detail?: string }[];
        dropped?: readonly string[];
        idPrefix?: string;
        heading?: boolean;
        optionLabel?: (key: string, option: string) => string | undefined;
    }

    const { schema, values, t, onChange, busyKey = null, error = null, warnings = [], dropped = [], idPrefix = 'sf', heading = true, optionLabel }: Props = $props();

    function wordsFor(key: string, labelKey: string, option: string): string {
        return optionLabel?.(key, option) ?? t(`${labelKey}.option.${option}`);
    }

    let formEl = $state<HTMLElement | null>(null);

    $effect(() => {
        const refused = error;
        if (!refused || !formEl) return;
        const field = schema.fields[refused.key];
        if (!field) return;
        untrack(() => {
            const wanted = `${idPrefix}-${refused.key}`;
            for (const el of formEl?.querySelectorAll<HTMLInputElement | HTMLSelectElement>('input, select') ?? []) {
                if (el.id === wanted) el.value = String(shown(refused.key, field));
            }
        });
    });

    const entries = $derived(Object.entries(schema.fields) as [string, WidgetSettingField][]);
    const groups = $derived(settingGroups(schema));
    const busy = $derived(busyKey !== null);

    function chosen(key: string): boolean {
        return Object.prototype.hasOwnProperty.call(values, key);
    }

    function shown(key: string, field: WidgetSettingField): SettingValue {
        return resolveValue(field, values[key]);
    }

    function commitNumber(key: string, input: HTMLInputElement): void {
        const parsed = input.valueAsNumber;
        onChange(key, Number.isFinite(parsed) ? parsed : input.value);
    }

    function commitText(key: string, field: WidgetSettingField, input: HTMLInputElement): void {
        if (input.value === shown(key, field)) return;
        onChange(key, input.value);
    }

    function hint(field: WidgetSettingField): string {
        if (field.hintKey) return t(field.hintKey);
        if (field.kind === 'number' && field.min !== undefined && field.max !== undefined) {
            return t('item_settings.hint.range', { min: field.min, max: field.max });
        }
        if (field.kind === 'number' && field.min !== undefined) return t('item_settings.hint.min', { min: field.min });
        if (field.kind === 'number' && field.max !== undefined) return t('item_settings.hint.max', { max: field.max });
        if (field.kind === 'string') return t('item_settings.hint.length', { length: field.maxLength });
        return '';
    }
</script>

<section class="sf" bind:this={formEl} data-oc-base aria-labelledby={heading ? `${idPrefix}-title` : undefined} aria-label={heading ? undefined : t('item_settings.title')} data-settings-form>
    {#if heading}<h3 class="sf__title oc-label" id={`${idPrefix}-title`}>{t('item_settings.title')}</h3>{/if}
    {#if entries.length === 0}
        <p class="sf__empty">{t('item_settings.none')}</p>
    {/if}
    {#if dropped.length > 0}
        <p class="sf__notice" role="status">{t('item_settings.dropped', { keys: dropped.join(', ') })}</p>
    {/if}
    {#each groups as group, at (group.labelKey ?? at)}
        <div class="sf__group" data-settings-group={group.labelKey ?? ''} role="group" aria-label={group.labelKey ? t(group.labelKey) : undefined}>
            {#if group.labelKey}<h4 class="sf__group-head">{t(group.labelKey)}</h4>{/if}
            {#if group.matrix}
                <SettingsMatrix matrix={group.matrix} fields={schema.fields} {values} {t} {onChange} {busy} {error} idPrefix={`${idPrefix}-${at}`} />
            {:else}
                {#each group.fields as key (key)}
                    {@const field = schema.fields[key]!}
                    {@render row(key, field)}
                {/each}
            {/if}
        </div>
    {/each}
</section>

{#snippet row(key: string, field: WidgetSettingField)}
        {@const control = `${idPrefix}-${key}`}
        {@const words = hint(field)}
        <div class="sf__row" data-setting={key} data-kind={field.kind} data-chosen={chosen(key) ? '1' : '0'}>
            <label class="sf__label" for={control}>{t(field.labelKey)}</label>
            <div class="sf__control">
                {#if field.kind === 'boolean'}
                    {@const on = shown(key, field) === true}
                    <Switch
                        id={control}
                        bind:checked={() => on, (next) => onChange(key, next)}
                        disabled={busy || fieldDisabled(schema, key, values)}
                        data-on={on ? '1' : '0'}
                        label={busyKey === key ? t('item_settings.saving') : t(on ? 'item_settings.on' : 'item_settings.off')}
                    />
                {:else if field.kind === 'number'}
                    <input
                        id={control}
                        class="sf__input sf__input--number"
                        data-field
                        type="number"
                        inputmode="decimal"
                        step="any"
                        min={field.min}
                        max={field.max}
                        value={shown(key, field)}
                        disabled={busy}
                        aria-invalid={error?.key === key}
                        onchange={(event) => commitNumber(key, event.currentTarget)}
                    />
                {:else if field.kind === 'enum' && controlOf(field) === 'segmented'}
                    {@const current = shown(key, field)}
                    <Segmented
                        id={control}
                        label={t(field.labelKey)}
                        value={String(current)}
                        disabled={busy}
                        options={field.options.map((option) => ({ value: option, label: wordsFor(key, field.labelKey, option), attrs: { 'data-option': option } }))}
                        onchange={(next) => onChange(key, next)}
                    />
                {:else if field.kind === 'enum'}
                    <Select
                        id={control}
                        data-sf-input
                        aria-label={t(field.labelKey)}
                        value={String(shown(key, field))}
                        disabled={busy}
                        options={field.options.map((option) => ({ value: option, label: wordsFor(key, field.labelKey, option) }))}
                        onchange={(event) => onChange(key, (event.currentTarget as HTMLSelectElement).value)}
                    />
                {:else}
                    <input
                        id={control}
                        class="sf__input"
                        data-field
                        type="text"
                        maxlength={field.maxLength}
                        value={shown(key, field)}
                        disabled={busy}
                        aria-invalid={error?.key === key}
                        onchange={(event) => commitText(key, field, event.currentTarget)}
                    />
                {/if}
                {#if chosen(key)}
                    <Button data-sf-reset disabled={busy} onclick={() => onChange(key, null)}>
                        {t('item_settings.use_default')}
                    </Button>
                {:else}
                    <span class="sf__default">{t('item_settings.default')}</span>
                {/if}
            </div>
            {#if words}<p class="sf__hint">{words}</p>{/if}
            {#if error?.key === key}<p class="sf__error" role="alert">{error.text}</p>{/if}
            {#each warnings.filter((w) => w.field === key) as warning (`${warning.message}|${warning.detail ?? ''}`)}
                <p class="sf__warn" role="status" data-setting-warning>
                    <span class="sf__warn-message">{warning.message}</span>
                    {#if warning.detail}<span class="sf__warn-detail">{warning.detail}</span>{/if}
                </p>
            {/each}
        </div>
{/snippet}
