
<script lang="ts">
    import type { Snippet } from 'svelte';
    import { resourcePush } from '../../resource-push/boot';
    import type { Translate } from '../../sessions/types';
    import { createActions } from '../../publish-page/actions';
    import { browserPageHost } from '../../publish-page/host';
    import { createPageStore } from '../../publish-page/page-store.svelte';
    import PublishPage from '../../publish-page/PublishPage.svelte';
    import InstalledPage from './InstalledPage.svelte';
    import type { MenuSources } from './model';
    import type { MenuNode } from './route';

    interface Props {
        node: MenuNode;
        sources: MenuSources;
        t: Translate;
        onNavigate: (node: MenuNode) => void;
        onChanged?: () => void;
        catalogDetail?: Snippet<[string]>;
    }

    const { node, sources, t, onNavigate, onChanged, catalogDetail }: Props = $props();

    const host = browserPageHost();
    // svelte-ignore state_referenced_locally
    const store = createPageStore({ host, navigate: (next) => onNavigate(next), t });
    // svelte-ignore state_referenced_locally
    const actions = createActions({ store, host, t });
    const onPublish = $derived(node.scope === 'publish');
    let opened = false;

    $effect(() => {
        if (!onPublish) return;
        store.applyNode(node);
        if (!opened) {
            opened = true;
            void store.open();
        }
    });

    $effect(() => {
        if (!onPublish) return;
        return store.connect(resourcePush());
    });
</script>

{#if node.scope === 'publish'}
    <PublishPage {store} {actions} {t} />
{:else if node.scope === 'installed' || node.scope === 'look'}
    <InstalledPage {node} {sources} {t} {onNavigate} {onChanged} {catalogDetail} />
{/if}
