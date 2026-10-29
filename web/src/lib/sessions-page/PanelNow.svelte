
<script lang="ts">
    import type { SessionListItem, Translate } from '../sessions/types';
    import type { PageRow } from './filters';

    interface Props {
        row: PageRow;
        live: SessionListItem | undefined;
        listingDown: boolean;
        t: Translate;
        now: number;
    }
    const { row, live, listingDown, t, now }: Props = $props();

    const running = $derived(row.s.state === 'running');
    const peer = $derived(row.computer !== null);
    const helpers = $derived(typeof live?.subagents_total === 'number' && live.subagents_total > 0 ? t('sessions.page.panel.now.helpers_val', { running: live.subagents_running ?? 0, total: live.subagents_total }) : null);
    const background = $derived(typeof live?.background_open === 'number' && live.background_open > 0 ? t('sessions.page.panel.now.background_val', { count: live.background_open }) : null);
    const model = $derived.by((): string | null => {
        const l = live as (SessionListItem & { running_model?: string | null; running_context_used_pct?: number | null }) | undefined;
        if (!l?.running_model) return null;
        return typeof l.running_context_used_pct === 'number' ? t('sessions.page.panel.now.model_val', { model: l.running_model, pct: Math.round(l.running_context_used_pct) }) : l.running_model;
    });
    const timer = $derived.by((): string | null => {
        const at = live?.timers_next_fire_at ? Date.parse(live.timers_next_fire_at) : NaN;
        const min = Math.round((at - now) / 60000);
        return Number.isFinite(min) && min > 0 ? t('sessions.page.panel.now.timers_val', { min }) : null;
    });
</script>

{#if running && !peer}
    <section class="sp-pn-sec" id="sp-pn-now">
        <h3 class="pl-label">{t('sessions.page.panel.now')}</h3>
        {#if listingDown || !live}
            <p class="sp-pn-note">{t('sessions.page.panel.now.offline')}</p>
        {:else}
            <dl class="sp-pn-dl">
                {#if helpers}<dt>{t('sessions.page.panel.now.helpers')}</dt><dd>{helpers}</dd>{/if}
                {#if background}<dt>{t('sessions.page.panel.now.background')}</dt><dd>{background}</dd>{/if}
                {#if model}<dt>{t('sessions.page.panel.now.model')}</dt><dd>{model}</dd>{/if}
                <dt>{t('sessions.page.panel.now.timers')}</dt>
                <dd>{#if timer}{timer}{:else}<span class="sp-pn-dim">{t('sessions.page.panel.none')}</span>{/if}</dd>
            </dl>
        {/if}
    </section>
{/if}
