<!-- could not -->
<script lang="ts">
    import { t as reactiveT } from '../i18n/index.svelte';
    import { RUNNING_SESSION_KEYS } from '../../../../client/js/labels/running-session.js';
    import { wrapperPillView } from './running-row';
    import type { Translate } from '../sessions/types';

    interface Props {
        label?: string | null;
        t?: Translate;
    }

    let { label = null, t = reactiveT }: Props = $props();

    const view = $derived(wrapperPillView(label));
    const title = $derived(
        view ? t(RUNNING_SESSION_KEYS.wrapperTitle, { label: view.label }) : '',
    );
</script>

{#if view}
    <span class="wrapper-pill" {title} aria-label={title}>{view.label}</span>
{/if}
