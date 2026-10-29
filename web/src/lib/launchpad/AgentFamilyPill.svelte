
<script lang="ts">
    import { t as reactiveT } from '../i18n/index.svelte';
    import { FAMILY_PILL_KEYS, familyPillView } from './agent-family-pill';
    import type { Translate } from '../sessions/types';

    interface Props {
        family?: string | null;
        source?: string | null;
        t?: Translate;
    }

    let { family = null, source = null, t = reactiveT }: Props = $props();

    const view = $derived(familyPillView(family, source));
    const text = $derived(view.label ?? t(FAMILY_PILL_KEYS.unknownLabel));
    const title = $derived(t(view.titleKey, view.titleParams));
</script>

<span
    class="family-pill {view.className}"
    data-family-source={view.source}
>{text}</span>
