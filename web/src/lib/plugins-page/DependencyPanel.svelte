
<script lang="ts">
    import type { Translate } from '../sessions/types';
    import type { DependencyView, NeedRow } from './cplugs-adapter';

    interface Props {
        deps: DependencyView;
        name: string;
        t: Translate;
    }

    const { deps, name, t }: Props = $props();

    function needTone(status: NeedRow['status']): 'ok' | 'warn' | 'high' {
        return status === 'ok' ? 'ok' : status === 'off' ? 'warn' : 'high';
    }
</script>

<section class="plp-region" data-cplug-deps aria-label={t('plugins.page.deps.needs')}>
    <h3 class="pl-label">{t('plugins.page.deps.needs')}</h3>
    <ul class="plp-rows" data-cplug-needs>
        {#each deps.needs as need (`${need.kind}:${need.id}`)}
            <li class="plp-row" data-need-kind={need.kind} data-need-id={need.id} data-need-status={need.status}>
                <span class="plp-row__main">{need.label}<span class="plp-row__sub">{t(`plugins.page.deps.kind.${need.kind}`)}</span></span>
                <span class="plp-tag" data-tone={needTone(need.status)}>{t(`plugins.page.deps.status.${need.status}`)}</span>
            </li>
        {:else}
            <li class="plp-row plp-row--empty">{t('plugins.page.deps.needs_nothing')}</li>
        {/each}
    </ul>
    <h3 class="pl-label">
        {t('plugins.page.deps.needed_by')}
        {#if deps.neededBy.length}<span class="plp-label__count">{deps.neededBy.length}</span>{/if}
    </h3>
    <ul class="plp-rows" data-cplug-needed-by>
        {#each deps.neededBy as by (by.id)}
            <li class="plp-row" data-needed-by-id={by.id} data-needed-by-enabled={by.enabled}>
                <span class="plp-row__main">{by.label}<span class="plp-row__sub">{t('plugins.page.deps.kind.plugin')}</span></span>
                <span class="plp-tag" data-tone={by.enabled ? 'ok' : 'off'}>{t(by.enabled ? 'plugins.page.deps.on' : 'plugins.page.deps.off')}</span>
            </li>
        {:else}
            <li class="plp-row plp-row--empty">{t('plugins.page.deps.needed_by_nobody', { name })}</li>
        {/each}
    </ul>
</section>
