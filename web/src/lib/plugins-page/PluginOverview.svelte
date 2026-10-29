
<script lang="ts">
    import type { Translate } from '../sessions/types';
    import type { CplugItem } from './cplugs-adapter';
    import DependencyPanel from './DependencyPanel.svelte';
    import { surfaceChips } from './plugin-pane';

    interface Props {
        plugin: CplugItem;
        t: Translate;
    }

    const { plugin, t }: Props = $props();

    const chips = $derived(surfaceChips(plugin.surfaces, t));
    const removed = $derived(plugin.state === 'removed');
</script>

{#if plugin.brief}
    <div class="plp-region">
        <p class="plp-brief" data-plugin-brief>{plugin.brief}</p>
    </div>
{/if}
<div class="plp-region">
    <h3 class="pl-label">{t('plugins.page.fact.state')}</h3>
    <dl class="mgr-facts" data-cplug-facts>
        <dt>{t('plugins.page.pane.fact.now')}</dt>
        <dd data-plugin-now>{t(`plugins.page.state.${plugin.state}`)}</dd>
        {#if plugin.blockedBy.length}
            <dt>{t('plugins.page.fact.waiting_for')}</dt>
            <dd data-cplug-blocked-by>{plugin.blockedBy.join(', ')}</dd>
        {/if}
        {#if plugin.enabled === false && plugin.permissions.length}
            <dt>{t('plugins.page.pane.fact.turning_on')}</dt>
            <dd>{t('plugins.page.pane.turning_on', { count: plugin.permissions.length })}</dd>
        {/if}
    </dl>
</div>
{#if !removed}
    <div class="plp-region">
        <h3 class="pl-label">{t('plugins.page.pane.adds')}</h3>
        {#if chips.length}
            <ul class="plp-chips" data-plugin-adds>
                {#each chips as chip (chip.key)}
                    <li class="plp-chip" data-surface={chip.key}>{chip.label}{#if chip.count !== null}<span class="plp-chip__count">{chip.count}</span>{/if}</li>
                {/each}
            </ul>
        {:else}
            <p class="plp-note" data-plugin-adds-nothing>{t('plugins.page.pane.adds_nothing')}</p>
        {/if}
    </div>
    <DependencyPanel deps={plugin.deps} name={plugin.name} {t} />
{/if}
<div class="plp-region">
    <dl class="mgr-facts">
        {#if plugin.version}
            <dt>{t('plugins.page.fact.version')}</dt>
            <dd>{plugin.version}{#if plugin.byline}{' '}<span class="plp-dim">{plugin.byline}</span>{/if}</dd>
        {/if}
        <dt>{t('plugins.page.fact.id')}</dt>
        <dd data-plugin-id>{plugin.cplugId}</dd>
        {#if plugin.thirdParty}
            <dt>{t('plugins.page.fact.trust')}</dt>
            <dd data-plugin-trust>{t(plugin.unverified ? 'plugins.page.fact.trust_unverified' : 'plugins.page.fact.trust_third_party')}</dd>
            {#if plugin.changedFiles.length}
                <dt>{t('plugins.page.fact.changed_files')}</dt>
                <dd data-plugin-changed>{plugin.changedFiles.join(', ')}</dd>
            {/if}
            {#if plugin.publisher}
                <dt>{t('plugins.page.fact.publisher')}</dt>
                <dd data-plugin-publisher>{plugin.publisher}</dd>
            {/if}
            {#if plugin.tools.length}
                <dt>{t('plugins.page.fact.tools')}</dt>
                <dd data-plugin-tools>{plugin.tools.join(', ')}</dd>
            {/if}
        {/if}
    </dl>
</div>
