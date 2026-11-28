
<script lang="ts">
    import { onMount } from 'svelte';
    import NumberField from '../base/NumberField.svelte';
    import Select from '../base/Select.svelte';
    import Switch from '../base/Switch.svelte';
    import type { Translate } from '../sessions/types';
    import {
        COMET_COLORS, COMET_COLOR_FIELD, COMET_LAP_FIELD, COMET_LAP_MAX, COMET_LAP_MIN, COMET_ON_FIELD,
        comet, lapInRange, saveComet, startComet, type CometColor,
    } from './comet-pref.svelte';

    interface Props {
        t: Translate;
    }
    const { t }: Props = $props();

    onMount(() => startComet());

    let draft = $state<number | null>(null);
    let problem = $state<string | null>(null);
    const shown = $derived(draft ?? comet.lap);

    async function commitLap(value: number | null): Promise<void> {
        draft = value;
        if (value === null || !lapInRange(value)) {
            problem = t('settings.comet.lap_range', { min: COMET_LAP_MIN, max: COMET_LAP_MAX });
            return;
        }
        problem = (await saveComet(COMET_LAP_FIELD, value)) ?? null;
        if (problem === null) draft = null;
    }
</script>

<div class="cm">
    <Switch
        label={t('settings.comet.on')}
        bind:checked={() => comet.on, (next) => void saveComet(COMET_ON_FIELD, next)}
        aria-label={t('settings.comet.on')}
        data-comet-setting="on"
    />
    {#if comet.on}
        <div class="cm__row">
            <NumberField
                label={t('settings.comet.lap')}
                help={t('settings.comet.lap_help')}
                min={COMET_LAP_MIN}
                max={COMET_LAP_MAX}
                step={0.5}
                inputmode="decimal"
                value={shown}
                error={problem ?? undefined}
                onchange={(value) => void commitLap(value)}
                data-comet-setting="lap"
            />
            <Select
                label={t('settings.comet.color')}
                value={comet.color}
                options={COMET_COLORS.map((id) => ({ value: id, label: t(`settings.comet.color.${id}`) }))}
                onchange={(event) => void saveComet(COMET_COLOR_FIELD, (event.currentTarget as HTMLSelectElement).value as CometColor)}
                data-comet-setting="color"
            />
        </div>
    {/if}
</div>

<style>
  @layer components {
    .cm {
        display: flex;
        flex-direction: column;
        gap: var(--oc-space-3);
        min-width: 0;
    }
    .cm__row {
        display: flex;
        flex-wrap: wrap;
        gap: var(--oc-space-3);
        min-width: 0;
    }
  }
</style>
