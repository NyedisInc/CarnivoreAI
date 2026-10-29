
<script lang="ts">
    import Icon from '../../opscenter/ui/Icon.svelte';
    import Button from '../base/Button.svelte';
    import KindMark from '../catalog/KindMark.svelte';
    import Panel from './Panel.svelte';
    import type { PageProps } from './props';
    import { GATE_IDS } from './report-format';
    import { kindPanel, limitSentences, limitsLine } from './rules-model';
    import './rules.css';

    const { store, t }: PageProps = $props();

    const kinds = $derived(kindPanel(store.rules, t));
    const line = $derived(store.limits ? limitsLine(store.limits, t) : '');
    const sentences = $derived(store.limits ? limitSentences(store.limits, t, Date.now()) : []);
    const account = $derived(store.account);
    const handleText = $derived(
        !store.signedIn ? t('skill.publish.signed_out')
            : account?.handle ? t(account.handle_status === 'pending' ? 'skill.publish.handle.pending' : 'skill.publish.handle.confirmed', { handle: account.handle })
            : t('skill.publish.handle.lead'),
    );
</script>

{#snippet close()}
    <span class="d-back"><Button onclick={() => store.closeRules()}><Icon name="arrow-left" size={14} /> {t('publish.page.rules.close')}</Button></span>
{/snippet}

<div class="d-rules" data-pp="RulesView">
    {@render close()}
    <h2 class="d-name">{t('publish.page.rules.title')}</h2>
    <p class="d-lead d-lead--first">{t('skill.publish.lead')}</p>
    <Panel label={t('publish.page.rules.path')}>
        <ol>
            <li>{t('publish.page.rules.path_check')}</li>
            <li>{t('publish.page.rules.path_image')}</li>
            <li>{t('publish.page.rules.path_send', { count: GATE_IDS.length })}</li>
            <li>{t('publish.page.rules.path_review')}</li>
        </ol>
    </Panel>
    <Panel label={t('publish.page.rules.kinds')}>
        {#if store.failure.rules}<p class="d-rules__fail" role="alert">{store.failure.rules}</p>{/if}
        <dl>
            {#each kinds as row (row.tab)}
                <dt><KindMark kind={row.word} size="md" bare {t} />{t(`skill.publish.kind.${row.word}`)}</dt>
                <dd data-open={row.open ? '' : undefined}>{row.text}</dd>
            {/each}
        </dl>
    </Panel>
    <Panel label={t('publish.page.rules.limits')} id="d-rules-limits">
        {#if store.failure.limits}<p class="d-rules__fail" role="alert">{store.failure.limits}</p>{/if}
        {#if line}<p>{line}.</p>{/if}
        <ul class="d-plain">{#each sentences as sentence (sentence)}<li>{sentence}</li>{/each}</ul>
    </Panel>
    <Panel label={t('publish.page.rules.card_image')}>
        <p>{t('skill.publish.hero.hint')}</p>
        <p>{t('publish.new.hero_default')}</p>
    </Panel>
    <Panel label={t('publish.page.rules.handle')}><p>{handleText}</p></Panel>
    <div class="d-rules__end">{@render close()}</div>
</div>
