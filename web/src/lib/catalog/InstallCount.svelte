
<script lang="ts">
    import { SKILL_KEYS, reasonOf } from '../../../../client/js/labels/skill.js';
    import type { Translate } from '../sessions/types';
    import type { CatalogHost } from './catalog';
    import { installsView } from './install-report';
    import type { ItemInstalls } from './types';

    interface Props {
        itemId: string | null;
        host: CatalogHost;
        t: Translate;
    }

    const { itemId, host, t }: Props = $props();

    let body = $state<ItemInstalls | null>(null);
    let loading = $state(false);
    let failure = $state<string | null>(null);

    const view = $derived(installsView(body));

    $effect(() => {
        const id = itemId;
        body = null;
        failure = null;
        if (!id) return;
        let cancelled = false;
        loading = true;
        void (async () => {
            try {
                const answer = await host.itemInstalls(id);
                if (!cancelled) body = answer;
            } catch (error) {
                if (!cancelled) failure = reasonOf(error, t);
            } finally {
                if (!cancelled) loading = false;
            }
        })();
        return () => {
            cancelled = true;
        };
    });
</script>

{#if loading}
    <span class="installs">{t(SKILL_KEYS.installsLoading)}</span>
{:else if failure}
    
    <span class="installs installs--out" role="status">
        {t(SKILL_KEYS.installsUnavailable, { reason: failure })}
    </span>
{:else if view.shape === 'none'}
    
    <span class="installs">{t(SKILL_KEYS.installsNone)}</span>
{:else if view.shape === 'counted'}
    <span class="installs installs__count">
        {t(SKILL_KEYS.installsCount, { count: view.count })}
    </span>
{/if}

<style>
  @layer components {
    .installs {
        color: var(--cat-muted);
        font-family: var(--cat-mono);
        font-size: 11px;
        overflow-wrap: anywhere;
    }

    .installs--out {
        color: var(--cat-attention);
    }
  }
</style>
