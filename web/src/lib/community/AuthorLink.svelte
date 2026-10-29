
<script lang="ts">
    import type { Translate } from '../sessions/types';
    import Button from '../base/Button.svelte';
    import AuthorPage from './AuthorPage.svelte';
    import Identicon from './Identicon.svelte';
    import { browserCommunityHost, type CommunityHost } from './community';

    interface Props {
        t: Translate;
        handle: string;
        publisher?: boolean | null;
        host?: CommunityHost;
    }

    const { t, handle, publisher = false, host = browserCommunityHost() }: Props = $props();

    let open = $state(false);
</script>

<span class="alink" class:alink--open={open}>
    <span class="alink__row">
        <Button variant="quiet" size="sm" aria-expanded={open} onclick={() => { open = !open; }}>
            <Identicon {handle} size={14} />
            <span class="alink__handle">{handle}</span>
        </Button>
        {#if publisher}
            <span class="alink__badge">{t('community.badge.publisher')}</span>
        {/if}
    </span>
    {#if open}
        <AuthorPage {t} {host} {handle} />
    {/if}
</span>

<style>
  @layer components {
    .alink { display: inline-flex; flex-direction: column; align-items: flex-start; gap: var(--oc-space-1); }
    .alink--open { flex: 1 1 100%; align-items: stretch; }
    .alink__row { display: inline-flex; align-items: center; gap: var(--oc-space-1-5); }
    .alink__handle { overflow-wrap: anywhere; }
    .alink__badge {
        padding: 0 var(--oc-space-1);
        border: 1px solid var(--cat-action-edge);
        border-radius: 2px;
        color: var(--cat-action);
        font-family: var(--cat-mono);
        font-size: var(--oc-fs-micro, 10px);
        text-transform: uppercase;
        letter-spacing: 0.04em;
    }
  }
</style>
