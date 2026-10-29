
<script lang="ts">
    import type { Snippet } from 'svelte';
    import RankPanel, { type RankRow } from '../../opscenter/ui/RankPanel.svelte';
    import { providerMark } from '../sessions/agent-marks';
    import type { Translate } from '../sessions/types';
    import { sortCensus } from './census-model';
    import type { Census } from './skills-types';

    interface Props {
        census: Census;
        query: string;
        t: Translate;
        where?: Snippet;
    }

    const { census, query, t, where }: Props = $props();

    const rows = $derived<RankRow[]>(
        sortCensus(census.skills, query, 'd30', 'desc').map((row) => ({
            id: row.name,
            name: row.name,
            iconSvg: providerMark(row.harnesses[0] ?? null, 12).svg,
            icon: 'skill',
            tags: [
                ...row.harnesses.map((h) => t(`skills.harness.${h}`)),
                ...row.scopes.map((s) => t(`skills.census.scope.${s}`)),
            ],
            line: t('skills.page.tokens', { count: row.tokens_est }),
            metric: row.fires === null ? null : { value: String(row.fires.d30), unit: t('skills.census.fires') },
        })),
    );
</script>

<div class="sk-census" data-skills-census>
    {#if census.state === 'not_measured'}
        <p class="sk-note" role="status" data-census-unmeasured>{t('skills.census.unmeasured')}</p>
    {/if}
    <RankPanel
        label={t('skills.census.label')}
        {rows}
        ranked
        columns={{ name: t('skills.census.col.name'), metric: t('skills.census.col.d30') }}
        notMeasured={t('skills.census.not_measured')}
        empty={t('skills.page.empty')}
        headExtra={where}
        separated
    />
</div>
