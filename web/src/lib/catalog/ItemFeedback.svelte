
<script lang="ts">
    import CommentThread from '../community/CommentThread.svelte';
    import ItemNotePopup from './ItemNotePopup.svelte';
    import ItemRatings from './ItemRatings.svelte';
    import type { RatingsReader } from './ratings-reader.svelte';
    import type { CatalogHost } from './catalog';
    import { browserCatalogHost } from './catalog';
    import { t } from '../i18n/index.svelte';
    import { isReadonly } from './readonly';

    interface Props {
        itemId: string | null;
        showUnrateable?: boolean;
        reader: RatingsReader;
        host?: CatalogHost;
        installed?: boolean;
    }

    const { itemId, showUnrateable = false, reader, host = browserCatalogHost(), installed = true }: Props = $props();
    const readonly = isReadonly();

    let myLogin = $state<string | null>(null);

    let signedIn = $state(false);

    let guest = $state(false);

    // there is nothing
    $effect(() => {
        if (!itemId) {
            signedIn = false;
            guest = false;
            myLogin = null;
            return;
        }
        let cancelled = false;
        void (async () => {
            try {
                const session = await host.catalogSession();
                if (cancelled) return;
                signedIn = session?.signed_in === true;
                guest = session?.kind === 'guest';
                myLogin = signedIn ? (session?.login ?? null) : null;
            } catch {
                if (!cancelled) {
                    signedIn = false;
                    guest = false;
                    myLogin = null;
                }
            }
        })();
        return () => {
            cancelled = true;
        };
    });
</script>

{#if (itemId || showUnrateable) && !readonly}
    {#if !itemId}
        <section class="tfb-unrateable">
            <h3 class="tfb-label">{t('themes.page.feedback.heading')}</h3>
            <p class="tfb-note">{t('themes.page.feedback.unrateable')}</p>
        </section>
    {:else}
        <div class="tfb-cat">
            <ItemRatings {itemId} {host} {t} {signedIn} {guest} {installed} {myLogin} {reader} />
            <CommentThread {itemId} {t} {signedIn} {installed} ratings={reader.view.texts} />
            <div class="tfb-corner">
                <ItemNotePopup {itemId} {signedIn} />
            </div>
        </div>
    {/if}
{/if}

<style>
  @layer components {
    :global(.tfb-cat) {
        --cat-ground: var(--oc-ground-page);
        --cat-panel: var(--oc-ground-panel);
        --cat-raised: var(--oc-ground-raised);
        --cat-line: var(--oc-line-rule);
        --cat-line-quiet: var(--oc-line-faint);
        --cat-text: var(--oc-text-primary);
        --cat-muted: var(--oc-text-secondary);
        --cat-faint: var(--oc-text-muted);
        --cat-action: var(--oc-orange);
        --cat-action-edge: var(--oc-orange-dim);
        --cat-action-wash: var(--oc-orange-tint);
        --cat-attention: var(--oc-yellow);
        --cat-failure: var(--oc-coral);
        --cat-failure-wash: color-mix(in srgb, var(--oc-coral) 12%, var(--oc-ground-panel));
        --cat-mono: var(--font-mono);
        --cat-gutter: 16px;

        display: flex;
        flex-direction: column;
        gap: 10px;
    }

    .tfb-corner {
        display: flex;
        justify-content: flex-end;
    }

    .tfb-unrateable {
        display: flex;
        flex-direction: column;
        gap: 6px;
        padding-top: 6px;
        border-top: 1px solid var(--oc-line-faint);
    }

    .tfb-label {
        margin: 0;
        font-size: var(--oc-fs-micro, 10px);
        font-weight: 600;
        letter-spacing: var(--oc-tracking-label, 0.08em);
        text-transform: uppercase;
        color: var(--oc-text-dim);
    }

    .tfb-note {
        margin: 0;
        font-size: var(--oc-fs-label, 12px);
        line-height: 1.5;
        color: var(--oc-text-dim);
    }
  }
</style>
