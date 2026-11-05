
<script lang="ts">
    import { onMount } from 'svelte';
    import Segmented from '../../base/Segmented.svelte';
    import type { Translate } from '../../sessions/types';
    import { RAIL_MAGNIFY_PERCENTS, railMagnify } from '../../sidebar-widgets/rail-magnify';
    import { settingsDoc } from '../settings-doc.svelte';
    import { settingKey, type SettingDef } from '../settings-registry';

    interface Props {
        def: SettingDef;
        t: Translate;
    }

    const { def, t }: Props = $props();

    let percent = $state(railMagnify.read());
    onMount(() => railMagnify.follow((next) => (percent = next)));

    const options = RAIL_MAGNIFY_PERCENTS.map((value) => ({ value: String(value), label: t(`settings.rail_magnify.option.${value}`), attrs: { 'data-rail-magnify': String(value) } }));
    const busy = $derived(settingsDoc.status[def.id]?.state === 'saving');

    function pick(next: string): void {
        const before = percent;
        percent = Number(next);
        void settingsDoc.track(def.id, async () => {
            const why = await railMagnify.save(percent);
            if (why) percent = before;
            return why;
        });
    }
</script>

<Segmented {options} value={String(percent)} label={t(settingKey(def.id, 'label'))} disabled={busy} onchange={pick} />
