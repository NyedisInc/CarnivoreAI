
<script lang="ts">
    import { tick, untrack } from 'svelte';
    import { ELITE_KEYS as K } from '../../../../client/js/labels/warez-elite.js';
    import { refusalCodeOf } from '../catalog/install-actions';
    import { isGateRefusal, MAX_COMMENT_CHARS, type Comment, type CommunityHost } from '../community/community';
    import type { Translate } from '../sessions/types';

    interface Props {
        itemId: string | null;
        host: CommunityHost;
        t: Translate;
        say: (text: string) => void;
    }

    const { itemId, host, t, say }: Props = $props();

    const MAX_LINE = 90;
    const SETTLE_MS = 200;
    const BLUR_MS = 120;
    const HIDDEN = new Set(['hidden', 'removed', 'deleted']);

    let rows = $state.raw<Comment[]>([]);
    let more = $state(false);
    let open = $state(false);
    let posting = $state(false);
    let value = $state('');
    let input = $state<HTMLInputElement | null>(null);
    let addButton = $state<HTMLButtonElement | null>(null);
    let gen = 0;

    const shown = $derived(rows.filter((c) => !(c.status && HIDDEN.has(c.status) && !c.placeholder) && (c.placeholder || c.body)));
    const count = $derived(`(${shown.length}${more ? '+' : ''})`);

    $effect(() => {
        const id = itemId;
        const mine = ++gen;
        rows = [];
        more = false;
        untrack(() => { open = false; value = ''; });
        if (!id) return;
        const timer = setTimeout(async () => {
            try {
                const page = await host.comments(id);
                if (mine !== gen) return;
                rows = page.comments ?? [];
                more = !!page.cursor;
            } catch {
                if (mine === gen) rows = [];
            }
        }, SETTLE_MS);
        return () => clearTimeout(timer);
    });

    export async function begin(): Promise<boolean> {
        if (!itemId) return false;
        if (!open) {
            open = true;
            value = '';
        }
        await tick();
        input?.focus();
        return true;
    }
    export function editing(): boolean {
        return open;
    }

    function cancel(): void {
        open = false;
        value = '';
        void tick().then(() => addButton?.focus({ preventScroll: true }));
    }

    function sentence(error: unknown): string {
        const code = refusalCodeOf(error);
        const status = (error as { status?: unknown } | null)?.status;
        if (status === 401 || code === 'unauthorized' || isGateRefusal(error)) return t(K.commentSignin);
        const reason = code === 'install_required' ? t('community.not_installed') : code === 'rate_limited' ? t('community.error.rate_limited') : t('community.error.generic');
        return t(K.echoCommentFailed, { reason });
    }

    async function post(): Promise<void> {
        const id = itemId;
        const body = value.trim();
        if (!id || !body || posting) return;
        posting = true;
        try {
            const sent = await host.post(id, { body });
            if (id !== itemId) return;
            if (sent?.comment) rows = [sent.comment, ...rows];
            else {
                const page = await host.comments(id);
                rows = page.comments ?? [];
                more = !!page.cursor;
            }
            open = false;
            value = '';
            void tick().then(() => addButton?.focus({ preventScroll: true }));
        } catch (error) {
            say(sentence(error));
        } finally {
            posting = false;
        }
    }

    function onKeydown(e: KeyboardEvent): void {
        if (e.key === 'Enter') {
            e.preventDefault();
            void post();
        } else if (e.key === 'Escape') {
            e.preventDefault();
            e.stopPropagation();
            cancel();
        }
    }

    function onBlur(): void {
        setTimeout(() => {
            if (open && !posting && document.activeElement !== input) cancel();
        }, BLUR_MS);
    }

    function who(c: Comment): string {
        return c.author?.handle || c.login || t(K.commentGuest);
    }
</script>

<h3 class="dz-k">{t(K.dizSecComments)} <span class="dz-cn dz-dim">{count}</span></h3>
<ul class="dz-cm">
    {#each shown as c, i (c.comment_id ?? i)}
        {#if c.placeholder}
            <li class="dz-c dz-dim">{c.placeholder}</li>
        {:else}
            <li class="dz-c" class:mine={!!c.status}><span class="dz-ch-n">{who(c)}</span><span class="dz-ch-s">&gt;</span> {c.body}{#if c.status === 'held'} <span class="dz-dim">{t(K.commentHeld)}</span>{/if}</li>
        {/if}
    {:else}
        <li class="dz-c dz-dim">{t(K.commentNone)}</li>
    {/each}
</ul>
<div class="dz-cadd">
    {#if open}
        <label class="dz-cl" for="dz-ci">{t(K.commentPrompt)}</label>
        <input
            id="dz-ci"
            class="dz-ci"
            type="text"
            maxlength={Math.min(MAX_LINE, MAX_COMMENT_CHARS)}
            autocomplete="off"
            spellcheck="false"
            data-keep
            aria-label={t(K.commentAria)}
            bind:this={input}
            bind:value
            onkeydown={onKeydown}
            onblur={onBlur}
        />
        <span class="dz-dim dz-chint">{t(K.commentHint)}</span>
    {:else}
        <button type="button" class="dz-act" data-act="comment" aria-keyshortcuts="Shift+M" bind:this={addButton} onclick={() => void begin()}>{t(K.commentAdd)}</button>
    {/if}
</div>
