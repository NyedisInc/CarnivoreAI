
<script lang="ts">
    import NumberField from '../../base/NumberField.svelte';
    import type { Translate } from '../../sessions/types';
    import { autoSleep } from '../../auto-sleep/auto-sleep-store.svelte';
    import { settingsDoc } from '../settings-doc.svelte';
    import { minutesRange } from './minutes-range';

    interface Props {
        t: Translate;
        inputId: string;
        settingId: string;
        field: 'idle_minutes' | 'unread_idle_minutes';
    }

    const { t, inputId, settingId, field }: Props = $props();

    void autoSleep.refresh(true);

    const data = $derived(autoSleep.data);
    const value = $derived(settingsDoc.value(settingId));
    const invalid = $derived(settingsDoc.invalidIds.includes(settingId));

    const range = $derived(minutesRange());
</script>

{#if data}
    <span class="st-unit">
        <NumberField
            id={inputId}
            inputmode="numeric"
            step={1}
            min={range.min}
            max={range.max}
            disabled={!data.enabled || (field === 'unread_idle_minutes' && data.unread_blocks_sleep !== false)}
            error={invalid ? t('settings.status.invalid') : undefined}
            value={typeof value === 'number' && !Number.isNaN(value) ? value : null}
            oninput={(event) => {
                const raw = (event.currentTarget as HTMLInputElement).value;
                settingsDoc.setDraft(settingId, raw === '' ? NaN : Number(raw));
            }}
        />
        <span class="st-unit__suffix" aria-hidden="true">{t('settings.unit.minutes')}</span>
    </span>
{:else}
    <span class="sf__hint">{t('auto_sleep.loading')}</span>
{/if}
