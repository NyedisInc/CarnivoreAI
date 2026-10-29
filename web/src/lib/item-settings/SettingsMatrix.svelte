
<script lang="ts">
    import type { Translate } from '../sessions/types';
    import Check from '../../opscenter/ui/Check.svelte';
    import type { SettingsMatrix, SettingsMatrixRow, WidgetSettingField } from '../../opscenter/widgets/types';
    import { resolveValue, type SettingValue } from './api';

    interface Props {
        matrix: SettingsMatrix;
        fields: Readonly<Record<string, WidgetSettingField>>;
        values: Readonly<Record<string, SettingValue>>;
        t: Translate;
        onChange: (key: string, value: SettingValue | null) => void;
        busy?: boolean;
        error?: { key: string; text: string } | null;
        idPrefix?: string;
    }

    const { matrix, fields, values, t, onChange, busy = false, error = null, idPrefix = 'sf' }: Props = $props();

    let asking = $state<{ key: string; textKey: string } | null>(null);

    function toggle(row: SettingsMatrixRow, key: string, next: boolean): void {
        const textKey = row.confirm?.[key];
        if (next && textKey) {
            asking = { key, textKey };
            return;
        }
        asking = null;
        onChange(key, next);
    }

    function confirmAsked(): void {
        if (!asking) return;
        const { key } = asking;
        asking = null;
        onChange(key, true);
    }

    function ticked(key: string): boolean {
        const field = fields[key];
        return field ? resolveValue(field, values[key]) === true : false;
    }
</script>

<div class="sf-matrix__frame">
    <table class="sf-matrix" data-settings-matrix id={`${idPrefix}-matrix`}>
        <thead>
            <tr>
                <th scope="col" class="sf-matrix__corner"></th>
                {#each matrix.columns as column (column)}
                    <th scope="col" class="sf-matrix__col" data-matrix-column={column}>{t(column)}</th>
                {/each}
            </tr>
        </thead>
        <tbody>
            {#each matrix.rows as row (row.labelKey)}
                <tr class="sf-matrix__row" data-matrix-row={row.labelKey} data-locked={row.locked ? '1' : '0'}>
                    <th scope="row" class="sf-matrix__label">
                        <span class="sf-matrix__words">{t(row.labelKey)}</span>
                        {#if row.hintKey}<span class="sf-matrix__hint">{t(row.hintKey)}</span>{/if}
                        {#if row.fields && error && row.fields.includes(error.key)}<span class="sf__error" role="alert">{error.text}</span>{/if}
                    </th>
                    {#if row.locked || !row.fields}
                        <td class="sf-matrix__locked" colspan={matrix.columns.length}>{t('item_settings.matrix.locked')}</td>
                    {:else}
                        {#each row.fields as key, at (key)}
                            {@const on = ticked(key)}
                            <td class="sf-matrix__cell" data-setting={key}>
                                <Check
                                    label=""
                                    bare
                                    checked={on}
                                    disabled={busy}
                                    ariaLabel={`${t(row.labelKey)}, ${t(matrix.columns[at] ?? '')}`}
                                    data-on={on ? '1' : '0'}
                                    onToggle={(next) => toggle(row, key, next)}
                                />
                            </td>
                        {/each}
                    {/if}
                </tr>
                {#if asking && row.fields?.includes(asking.key)}
                    <tr class="sf-matrix__ask" data-matrix-ask={asking.key}>
                        <td colspan={matrix.columns.length + 1}>
                            <p class="sf-matrix__ask-text" role="alert">{t(asking.textKey)}</p>
                            <div class="sf-matrix__ask-actions">
                                <button type="button" class="modal-btn modal-btn-secondary" data-matrix-ask-cancel disabled={busy}
                                    onclick={() => (asking = null)}>{t('item_settings.matrix.confirm_cancel')}</button>
                                <button type="button" class="modal-btn modal-btn-danger" data-matrix-ask-confirm disabled={busy}
                                    onclick={confirmAsked}>{t('item_settings.matrix.confirm_go')}</button>
                            </div>
                        </td>
                    </tr>
                {/if}
            {/each}
        </tbody>
    </table>
</div>
