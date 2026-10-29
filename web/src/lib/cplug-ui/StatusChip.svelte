
<script lang="ts">
    import type { Translate } from '../sessions/types';
    import { glanceBadge, type GlanceBadge } from './glance';
    import { watchSurface } from './surface.svelte';
    import type { Declared } from './validate';
    import './cplug-ui.css';

    interface Props {
        cplugId: string;
        installKey: string | null;
        declared: Declared;
        unverified?: boolean;
        t: Translate;
    }

    const { cplugId, installKey, declared, unverified = false, t }: Props = $props();
    let badge = $state<GlanceBadge | null>(null);

    $effect(() => watchSurface({ cplugId, installKey, surface: 'glance' }, (state) => {
        badge = state.kind === 'ready' ? glanceBadge(state.document, declared) : null;
    }));
</script>

{#if badge}
    <span class="cu-chip">
        <span class="cu-frame__mark" data-cplug-mark data-unverified={unverified ? '' : undefined}>{t(unverified ? 'cplug_ui.mark.unverified' : 'cplug_ui.mark.third_party')}</span>
        <span class="cu-badge" data-cplug-chip data-tone={badge.tone} data-status={badge.status}>{badge.status ? t(`cplug_ui.status.${badge.status}`) : badge.text}</span>
    </span>
{/if}
