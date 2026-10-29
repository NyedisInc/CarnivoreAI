
<script lang="ts">
    import type { Translate } from '../sessions/types';
    import { refusalCodeOf } from '../catalog/install-actions';
    import { browserPublishHost, type PublishHost } from '../catalog/publish';
    import RegisterGate from '../catalog/RegisterGate.svelte';
    import { GATE_CANCELLED, createRegisterGate } from '../catalog/register-gate.svelte';
    import AuthorLink from './AuthorLink.svelte';
    import Composer from './Composer.svelte';
    import Identicon from './Identicon.svelte';
    import RatingStars from '../rating/RatingStars.svelte';
    import type { RatingTextView } from '../catalog/ratings';
    import LinkedText from './LinkedText.svelte';
    import ReportDialog from './ReportDialog.svelte';
    import {
        browserCommunityHost,
        buildThread,
        canEdit,
        dayOf,
        type Comment,
        type CommunityHost,
        type ThreadNode,
    } from './community';

    interface Props {
        itemId: string | null;
        t: Translate;
        signedIn: boolean;
        installed?: boolean;
        host?: CommunityHost;
        publishHost?: PublishHost;
        ratings?: readonly RatingTextView[];
    }

    const {
        itemId,
        t,
        signedIn,
        installed = true,
        host = browserCommunityHost(),
        publishHost = browserPublishHost(),
        ratings = [],
    }: Props = $props();

    let pub = $state<Comment[]>([]);
    let mine = $state<Comment[]>([]);
    let more = $state<string | null>(null);
    let loading = $state(false);
    let failed = $state(false);
    let reloads = $state(0);
    let replying = $state<string | null>(null);
    let editing = $state<string | null>(null);
    let reporting = $state<string | null>(null);
    let myHandle = $state<string | null>(null);
    const canReply = $derived(
        signedIn && !!itemId && !!myHandle && myHandle.toLowerCase() === (itemId.split('/', 1)[0] ?? '').toLowerCase(),
    );
    const gate = createRegisterGate(() => publishHost, t('community.gate.failed'));

    const ratingNodes = $derived<ThreadNode[]>(
        ratings
            .filter((r) => r.text)
            .map((r) => ({
                comment: {
                    comment_id: `rating:${r.reviewRef ?? ''}`,
                    author: r.author ? { handle: r.author, publisher: r.publisher } : null,
                    login: r.login,
                    body: r.text,
                    created_at: r.updatedAt,
                    rating: r.stars,
                    review_ref: r.reviewRef,
                },
                mine: false,
                held: false,
                replies: [],
            })),
    );
    const tree = $derived.by(() => {
        const nodes = [...buildThread(pub, signedIn ? mine : []), ...ratingNodes];
        return ratingNodes.length
            ? nodes.sort((a, b) => (b.comment.created_at ?? 0) - (a.comment.created_at ?? 0))
            : nodes;
    });
    const nowSeconds = () => Math.floor(Date.now() / 1000);

    $effect(() => {
        myHandle = null;
        if (!signedIn) return;
        let cancelled = false;
        void (async () => {
            try {
                const account = await publishHost.account();
                if (!cancelled) myHandle = account?.handle || null;
            } catch {
                if (!cancelled) myHandle = null;
            }
        })();
        return () => { cancelled = true; };
    });

    $effect(() => {
        const id = itemId;
        void reloads;
        void signedIn;
        pub = [];
        mine = [];
        more = null;
        failed = false;
        replying = editing = reporting = null;
        if (!id) return;
        let cancelled = false;
        loading = true;
        void (async () => {
            try {
                const page = await host.comments(id);
                if (cancelled) return;
                pub = page.comments ?? [];
                more = page.cursor ?? null;
            } catch {
                if (!cancelled) failed = true;
            }
            if (signedIn && !cancelled) {
                try {
                    const own = await host.myComments(id);
                    if (!cancelled) mine = own.comments ?? [];
                } catch {
                    if (!cancelled) mine = [];
                }
            }
            if (!cancelled) loading = false;
        })();
        return () => { cancelled = true; };
    });

    async function loadMore(): Promise<void> {
        if (!itemId || !more) return;
        try {
            const page = await host.comments(itemId, more);
            pub = [...pub, ...(page.comments ?? [])];
            more = page.cursor ?? null;
        } catch {
            failed = true;
        }
    }

    function sentence(error: unknown): string {
        const code = refusalCodeOf(error);
        if (code === 'unauthorized') return t('community.signed_out');
        if (code === 'install_required') return t('community.not_installed');
        if (code === 'guest_cap_reached') return t('community.error.guest_cap');
        if (code === 'rate_limited') return t('community.error.rate_limited');
        if (code === 'comment_locked') return t('community.error.locked');
        return t('community.error.generic');
    }

    async function post(body: string, parent?: string): Promise<string | null> {
        if (!itemId) return null;
        try {
            const id = itemId;
            const sent = await gate.guard(() => host.post(id, parent ? { body, parent_id: parent } : { body }));
            // the registration prompt
            if (sent === GATE_CANCELLED) return t('community.gate.needed');
            replying = null;
            reloads += 1;
            return null;
        } catch (error) {
            return sentence(error);
        }
    }

    async function edit(commentId: string, body: string): Promise<string | null> {
        if (!itemId) return null;
        try {
            await host.edit(itemId, commentId, body);
            editing = null;
            reloads += 1;
            return null;
        } catch (error) {
            return sentence(error);
        }
    }

    async function remove(commentId: string): Promise<void> {
        if (!itemId) return;
        try {
            await host.remove(itemId, commentId);
            reloads += 1;
        } catch {
            failed = true;
        }
    }
</script>

{#snippet row(node: ThreadNode, reply: boolean)}
    {@const c = node.comment}
    {@const id = c.comment_id ?? ''}
    <li class="thr__item" class:thr__item--reply={reply} class:thr__item--held={node.held}>
        {#if c.placeholder}
            <p class="thr__gone">{t('community.placeholder')}</p>
        {:else}
            <div class="thr__meta">
                {#if c.author?.handle}
                    <AuthorLink {t} {host} handle={c.author.handle} publisher={c.author.publisher} />
                {:else if c.login}
                    <span class="thr__login"><Identicon handle={c.login} size={14} />{c.login}</span>
                {/if}
                {#if typeof c.rating === 'number'}
                    <RatingStars value={c.rating} size={12} label={t('skill.rating.average', { average: c.rating })} />
                {/if}
                {#if dayOf(c.created_at)}
                    <span class="thr__when">{dayOf(c.created_at)}</span>
                {/if}
                {#if c.edited}
                    <span class="thr__when">{t('community.edited')}</span>
                {/if}
                {#if node.held}
                    <span class="thr__held">{t('community.held')}</span>
                {/if}
            </div>
            {#if editing === id}
                <Composer {t} initial={c.body ?? ''} actionKey="community.save" onsubmit={(b) => edit(id, b)} oncancel={() => { editing = null; }} />
            {:else}
                <p class="thr__body"><LinkedText text={c.body ?? ''} /></p>
            {/if}
            <div class="thr__acts">
                {#if canReply && !reply && !node.held && !c.review_ref}
                    <button type="button" class="thr__act" onclick={() => { replying = replying === id ? null : id; }}>{t('community.reply')}</button>
                {/if}
                {#if node.mine && canEdit(c, nowSeconds())}
                    <button type="button" class="thr__act" onclick={() => { editing = id; }}>{t('community.edit')}</button>
                {/if}
                {#if node.mine}
                    <button type="button" class="thr__act" onclick={() => void remove(id)}>{t('community.delete')}</button>
                {:else}
                    <button type="button" class="thr__act" onclick={() => { reporting = reporting === id ? null : id; }}>{t('community.report')}</button>
                {/if}
            </div>
            {#if reporting === id && itemId}
                <ReportDialog {t} {host} target={c.review_ref ? { kind: 'review', itemId, reviewRef: c.review_ref } : { kind: 'comment', itemId, commentId: id }} onclose={() => { reporting = null; }} {gate} />
            {/if}
        {/if}
        {#if replying === id}
            <Composer {t} actionKey="community.reply.send" signedOut={!signedIn} locked={installed ? null : t('community.not_installed')} onsubmit={(b) => post(b, id)} oncancel={() => { replying = null; }} />
        {/if}
        {#if node.replies.length}
            <ul class="thr__list">
                {#each node.replies as child}
                    {@render row(child, true)}
                {/each}
            </ul>
        {/if}
    </li>
{/snippet}

<section class="thr" aria-label={t('community.heading')}>
    <p class="thr__heading">{t('community.heading')}</p>
    {#if loading}
        <p class="thr__note">{t('community.loading')}</p>
    {:else}
        
        {#if failed}
            <p class="thr__note thr__note--out" role="status">{t('community.failed')}</p>
        {:else if tree.length === 0}
            <p class="thr__note">{t('community.none')}</p>
        {/if}
        <ul class="thr__list">
            {#each tree as node}
                {@render row(node, false)}
            {/each}
        </ul>
        {#if more}
            <button type="button" class="modal-btn modal-btn-secondary" onclick={() => void loadMore()}>{t('community.more')}</button>
        {/if}
    {/if}

    <Composer {t} actionKey="community.post" signedOut={!signedIn} locked={installed ? null : t('community.not_installed')} onsubmit={(b) => post(b)} />

    <RegisterGate {gate} host={publishHost} {t} />
</section>

<style>
    .thr {
        display: flex;
        flex-direction: column;
        gap: 6px;
        padding: 10px 12px;
        border: 1px solid var(--cat-line);
        border-radius: 4px;
        background: var(--cat-panel);
    }
    .thr__heading {
        margin: 4px 0 0;
        color: var(--cat-muted);
        font-family: var(--cat-mono);
        font-size: 10px;
        text-transform: uppercase;
        letter-spacing: 0.04em;
    }
    .thr__list { display: flex; flex-direction: column; gap: 4px; margin: 0; padding: 0; list-style: none; }
    .thr__item { display: flex; flex-direction: column; gap: 3px; padding: 4px 0; border-top: 1px solid var(--cat-line-quiet); }
    .thr__item:first-child { border-top: none; }
    .thr__item--reply { margin-left: 14px; padding-left: 8px; border-left: 1px solid var(--cat-line); border-top: none; }
    .thr__item--held { border-left: 2px solid var(--cat-attention); padding-left: 8px; }
    .thr__meta { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; }
    .thr__login { display: inline-flex; align-items: center; gap: 5px; color: var(--cat-faint); font-family: var(--cat-mono); font-size: 10px; overflow-wrap: anywhere; }
    .thr__when { color: var(--cat-faint); font-family: var(--cat-mono); font-size: 10px; }
    .thr__held { color: var(--cat-attention); font-family: var(--cat-mono); font-size: 10px; text-transform: uppercase; letter-spacing: 0.04em; }
    .thr__body { margin: 0; color: var(--cat-text); font-size: 12px; line-height: 1.45; }
    .thr__gone { margin: 0; color: var(--cat-faint); font-size: 11px; font-style: italic; }
    .thr__acts { display: flex; gap: 10px; }
    .thr__act {
        padding: 0;
        border: none;
        background: transparent;
        color: var(--cat-muted);
        font-size: 11px;
        cursor: pointer;
    }
    .thr__act:hover { color: var(--cat-text); }
    .thr__note { margin: 0; color: var(--cat-muted); font-size: 12px; line-height: 1.45; }
    .thr__note--out {
        padding: 6px 8px;
        border-left: 2px solid var(--cat-attention);
        background: var(--cat-raised);
        color: var(--cat-text);
    }
    @media (max-width: 1023px) {
        .thr__act { min-height: 44px; padding: 0 8px; }
    }
    .thr :global(.modal-btn) {
        padding: 7px 16px;
        font-size: 13px;
    }
</style>
