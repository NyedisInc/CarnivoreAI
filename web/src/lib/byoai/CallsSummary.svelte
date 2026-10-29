
<script lang="ts">
    import type { Translate } from '../sessions/types';
    import type { CallsSummary, SpendRow } from './api';
    import { compact, costText, latencyText, modelName, percent } from './calls-logic';

    interface Props {
        t: Translate;
        summary: CallsSummary;
        featureName: (id: string) => string;
        onpick: (kind: 'feature' | 'model', key: string) => void;
    }
    const { t, summary, featureName, onpick }: Props = $props();

    const bySpend = $derived(summary.spend > 0);
    const weight = (row: SpendRow): number => (bySpend ? row.spend : row.calls);
    const share = (rows: SpendRow[], row: SpendRow): number => {
        const top = Math.max(...rows.map(weight), 0);
        return top ? Math.max(2, Math.round((weight(row) / top) * 100)) : 0;
    };
    const stats = $derived([
        ['calls', compact(summary.calls)],
        ['spend', costText(summary.spend)],
        ['errors', `${percent(summary.errors, summary.calls)}${summary.errors ? ` (${summary.errors})` : ''}`],
        ['latency', `${latencyText(summary.median_ms)} / ${latencyText(summary.p95_ms)}`],
        ['tokens', `${compact(summary.tokens_in)} / ${compact(summary.tokens_out)}`],
    ] as const);
</script>

<dl class="ai-strip" data-ai="calls-strip">
    {#each stats as [key, value] (key)}
        <div class="ai-strip__stat" data-error={key === 'errors' && summary.errors > 0 ? 'true' : undefined}>
            <dt class="ai-strip__label">{t(`settings.ai.calls.stat.${key}`)}</dt>
            <dd class="ai-strip__value" data-ai-stat={key}>{value}</dd>
        </div>
    {/each}
</dl>

{#if summary.by_feature.length > 0 || summary.by_model.length > 0}
    <div class="ai-spend" data-ai="calls-spend">
        {#each [['feature', summary.by_feature], ['model', summary.by_model]] as const as [kind, rows] (kind)}
            <div class="ai-spend__col">
                <h4 class="ai-spend__title">{t(`settings.ai.calls.spend.${kind}`)}</h4>
                {#each rows as row (row.key)}
                    <button type="button" class="ai-spend__row" data-ai-spend={kind} title={t('settings.ai.calls.spend.filter')}
                        onclick={() => onpick(kind, row.key)}>
                        <span class="ai-spend__name">{kind === 'feature' ? featureName(row.key) : modelName(row.key).name}</span>
                        <span class="ai-spend__num">{bySpend ? costText(row.spend) : t('settings.ai.calls.spend.calls', { n: row.calls })}</span>
                        <span class="ai-spend__bar" aria-hidden="true"><span class="ai-spend__fill" style:width="{share(rows, row)}%"></span></span>
                    </button>
                {/each}
            </div>
        {/each}
    </div>
{/if}
