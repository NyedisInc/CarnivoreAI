
<script lang="ts">
    import type { Translate } from '../sessions/types';
    import Identicon from './Identicon.svelte';
    import LinkedText from './LinkedText.svelte';
    import { safeHref } from './linkify';
    import type { CommunityHost, Profile } from './community';

    interface Props {
        t: Translate;
        host: CommunityHost;
        handle: string;
    }

    const { t, host, handle }: Props = $props();

    let profile = $state<Profile | null>(null);
    let failed = $state(false);

    $effect(() => {
        const who = handle;
        profile = null;
        failed = false;
        let cancelled = false;
        void (async () => {
            try {
                const answer = await host.profile(who);
                if (!cancelled) profile = answer;
            } catch {
                // its own sentence
                if (!cancelled) failed = true;
            }
        })();
        return () => { cancelled = true; };
    });

    const links = $derived((profile?.links ?? []).filter((l) => safeHref(l) !== null));
</script>

<section class="author" aria-label={t('community.author.heading', { handle })}>
    <div class="author__head">
        <Identicon {handle} size={28} />
        <span class="author__handle">{handle}</span>
        {#if profile?.publisher}
            <span class="author__badge">{t('community.badge.publisher')}</span>
        {/if}
    </div>
    {#if failed}
        <p class="author__note" role="status">{t('community.author.failed')}</p>
    {:else if !profile}
        <p class="author__note">{t('community.loading')}</p>
    {:else}
        {#if profile.joined}
            <p class="author__note">{t('community.author.joined', { when: profile.joined })}</p>
        {/if}
        {#if profile.bio}
            <p class="author__bio"><LinkedText text={profile.bio} /></p>
        {/if}
        {#if links.length}
            <ul class="author__list">
                {#each links as link}
                    <li><LinkedText text={link} /></li>
                {/each}
            </ul>
        {/if}
        <p class="author__label">{t('community.author.items')}</p>
        {#if profile.items && profile.items.length}
            <ul class="author__list">
                {#each profile.items as item}
                    <li class="author__item">{item}</li>
                {/each}
            </ul>
        {:else}
            <p class="author__note">{t('community.author.no_items')}</p>
        {/if}
    {/if}
</section>

<style>
  @layer components {
    .author {
        display: flex;
        flex-direction: column;
        gap: 4px;
        padding: 8px 10px;
        border: 1px solid var(--cat-line);
        border-radius: 3px;
        background: var(--cat-raised);
    }
    .author__head { display: flex; align-items: center; gap: 8px; }
    .author__handle { color: var(--cat-text); font-family: var(--cat-mono); font-size: 12px; overflow-wrap: anywhere; }
    .author__badge {
        padding: 0 5px;
        border: 1px solid var(--cat-action-edge);
        border-radius: 2px;
        color: var(--cat-action);
        font-family: var(--cat-mono);
        font-size: 10px;
        text-transform: uppercase;
        letter-spacing: 0.04em;
    }
    .author__label {
        margin: 4px 0 0;
        color: var(--cat-muted);
        font-family: var(--cat-mono);
        font-size: 10px;
        text-transform: uppercase;
        letter-spacing: 0.04em;
    }
    .author__note { margin: 0; color: var(--cat-muted); font-size: 11px; line-height: 1.45; }
    .author__bio { margin: 0; color: var(--cat-text); font-size: 12px; line-height: 1.45; }
    .author__list { margin: 0; padding: 0; list-style: none; font-size: 12px; color: var(--cat-text); }
    .author__item { font-family: var(--cat-mono); font-size: 11px; overflow-wrap: anywhere; }
  }
</style>
