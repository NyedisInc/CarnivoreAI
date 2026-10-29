
<script lang="ts">
    import { BROWSE_KEYS } from '../../../../client/js/labels/skill-browse.js';
    import type { Translate } from '../sessions/types';
    import type { CatalogHost } from './catalog';
    import type { SkillUsage } from './types';

    interface Props {
        skill: string;
        host: Pick<CatalogHost, 'skillUsage'>;
        windows?: boolean;
        t: Translate;
    }

    const { skill, host, t, windows = false }: Props = $props();

    let usage = $state<SkillUsage | null>(null);
    let settled = $state(false);

    $effect(() => {
        const name = skill;
        usage = null;
        settled = false;
        let cancelled = false;
        void (async () => {
            try {
                const answer = host.skillUsage ? await host.skillUsage(name) : null;
                if (!cancelled) usage = answer;
            } catch (error) {
                console.error('CloudeWeb: the skill usage read failed', error);
            } finally {
                if (!cancelled) settled = true;
            }
        })();
        return () => {
            cancelled = true;
        };
    });

    const fired = $derived(
        usage && usage.state === 'measured' && typeof usage.fired_30d === 'number' ? usage.fired_30d : null,
    );
    const fired7 = $derived(usage && usage.state === 'measured' && typeof usage.fired_7d === 'number' ? usage.fired_7d : null);
    const fired90 = $derived(usage && usage.state === 'measured' && typeof usage.fired_90d === 'number' ? usage.fired_90d : null);
</script>

{#if settled}
    <section class="cat-usage" aria-label={t(BROWSE_KEYS.usageHeading)}>
        <span class="cat-usage__heading">{t(BROWSE_KEYS.usageHeading)}</span>
        <p class="cat-usage__fact">
            {fired !== null
                ? t(BROWSE_KEYS.usageFired, { count: fired })
                : t(BROWSE_KEYS.usageNotMeasured)}
        </p>
        {#if windows && fired !== null}
            {#if fired7 !== null}<p class="cat-usage__fact" data-usage="7d">{t(BROWSE_KEYS.usageFired7, { count: fired7 })}</p>{/if}
            {#if fired90 !== null}<p class="cat-usage__fact" data-usage="90d">{t(BROWSE_KEYS.usageFired90, { count: fired90 })}</p>{/if}
        {/if}
    </section>
{/if}

<style>
    .cat-usage {
        display: flex;
        flex-direction: column;
        gap: 4px;
    }

    .cat-usage__heading {
        color: var(--cat-muted);
        font-family: var(--cat-mono);
        font-size: 10px;
        text-transform: uppercase;
        letter-spacing: 0.04em;
    }

    .cat-usage__fact {
        margin: 0;
        color: var(--cat-text);
        font-family: var(--cat-mono);
        font-size: 11px;
    }
</style>
