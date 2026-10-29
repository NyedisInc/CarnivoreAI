
<script lang="ts">
    import { sessionRowForConversation } from '../../cplugs/sdk/sessions.svelte';
    import { t } from '../i18n/index.svelte';
    import HitRow from '../deepsearch/HitRow.svelte';
    import { conversationName, conversationState, relativeWhen } from '../deepsearch/result-model';
    import { HIT_ID_PREFIX } from '../deepsearch/ids';
    import { searchD, topHits } from '../drawer/search-d.svelte';
    import Band from './Band.svelte';
    import SearchHead from './SearchHead.svelte';
    import Button from '../base/Button.svelte';
    import type { SearchConversationsPlan } from './search-plan';
    import '../deepsearch/search-d.css';
    import '../deepsearch/results.css';
    import './search-sections.css';

    let { s }: { s: SearchConversationsPlan } = $props();

    const c = $derived(searchD.controller);
    const shown = $derived(topHits());
    const now = new Date();
    const nothing = $derived(s.agents === 0 && (c === null || c.phase === 'short' || c.phase === 'idle' || c.phase === 'failed' || (c.phase === 'done' && c.total === 0)));
    const query = $derived(s.query);
    const noMatchKey = $derived(c === null ? 'drawer.search.nomatch.agents' : 'drawer.search.nomatch');
    const cursorHit = $derived(searchD.cursor - searchD.agentNames.length);
    let listEl = $state<HTMLElement | undefined>();

    $effect(() => () => { searchD.folded.conversations = false; });

    $effect(() => {
        if (cursorHit < 0) return;
        listEl?.querySelector(`#${HIT_ID_PREFIX}${cursorHit}`)?.scrollIntoView?.({ block: 'nearest' });
    });
</script>


{#if nothing || c !== null}
<Band kind="session-sidebar-search sd-scope" attrs={{ 'data-group': s.key, 'data-search-section': 'conversations' }}>
    {#if nothing}
        <div class="ssr-none" data-testid="search-nomatch" role="status">
            <p class="ssr-none__line">{t(noMatchKey, { query })}</p>
            <span class="ssr-none__acts">
                <Button variant="quiet" size="sm" data-search-next="conversations" onmousedown={(e) => e.preventDefault()} onclick={() => searchD.actions?.searchConversations()}>{t('drawer.search.nomatch.conversations')}</Button>
                <Button variant="quiet" size="sm" data-search-next="clear" onmousedown={(e) => e.preventDefault()} onclick={() => searchD.actions?.clear()}>{t('drawer.search.nomatch.clear')}<kbd class="ssr-key">{t('drawer.search.hint.clear')}</kbd></Button>
            </span>
        </div>
    {:else}
        {#if s.agents > 0}<div class="sd-rule" role="presentation"></div>{/if}
        <SearchHead label={t('drawer.search.conversations')} count={c?.phase === 'done' ? c.total : null} folded={searchD.folded.conversations}
            onfold={() => (searchD.folded.conversations = !searchD.folded.conversations)}
            action={c?.phase === 'done' && c.total > 0 ? { label: t('drawer.search.conv.deep'), next: 'conversations', run: () => searchD.actions?.searchConversations() } : undefined} />
        {#if searchD.folded.conversations}
            
        {:else if c === null || c.phase === 'short' || c.phase === 'idle'}
            <p class="ssr-line">{t('drawer.search.conv.short')}</p>
        {:else if c.phase === 'searching'}
            <p class="ssr-line" role="status">{t('drawer.search.conv.loading')}</p>
        {:else if c.phase === 'failed'}
            <p class="ssr-line" role="status">{t('drawer.search.conv.failed')}</p>
        {:else if shown.length === 0}
            <p class="ssr-line">{t('drawer.search.conv.none')}</p>
        {:else}
            <div bind:this={listEl} role="listbox" aria-label={t('deepsearch.results_label')} class="sd-list ssr-hits" data-testid="search-conversations">
                    {#each shown as top, i (top.group.conversationId)}
                        {@const live = sessionRowForConversation(top.group.conversationId)}
                        {@const conv = conversationState(top.group, live)}
                        {@const name = conversationName(top.group, live?.label, t)}
                        
                        <HitRow controller={c} group={top.group} hit={top.hit} {conv} {name} {live} id={`${HIT_ID_PREFIX}${i}`} picked={i === cursorHit}
                            meta={`${t(`deepsearch.kind.${top.hit.kind}`)}, ${relativeWhen(top.hit.at ?? top.group.lastActive, now, t)}`}
                            onopen={() => void c.pickHit(top.group, top.hit, name)} />
                    {/each}
            </div>
        {/if}
    {/if}
</Band>
{/if}
