
<script lang="ts">
    import AccountPanel from '../catalog/AccountPanel.svelte';
    import SessionsPanel from '../catalog/SessionsPanel.svelte';
    import { browserCatalogHost, type CatalogHost } from '../catalog/catalog';
    import Check from '../../opscenter/ui/Check.svelte';
    import Identicon from '../community/Identicon.svelte';
    import { displayName } from '../drawer-hud/account-identity';
    import { CATALOG_SESSION_EVENT, catalogAccount } from '../drawer-hud/catalog-account.svelte';
    import { t as appT } from '../i18n/index.svelte';
    import type { Translate } from '../sessions/types';
    import { browserAccountPageHost, type AccountPageHost } from './account-page-host';
    import { refreshAccount } from './account-store.svelte';
    import { openRegisterModal } from './open-register';
    import { openSignInModal } from './open-signin';
    import type { AccountFeature } from './features';

    interface Props {
        host?: CatalogHost;
        account?: AccountPageHost;
        t?: Translate;
    }

    const { host = browserCatalogHost(), account = browserAccountPageHost(), t = appT }: Props = $props();

    let news = $state<boolean | null>(null);
    let newsNote = $state<string | null>(null);
    let working = $state(false);

    const facts = $derived(catalogAccount.facts);
    const signedIn = $derived(facts?.signedIn === true);
    const guest = $derived(!signedIn && catalogAccount.guest);
    const handle = $derived(facts?.handle ?? '');
    const avatarSeed = $derived(displayName(handle, facts?.login ?? null) || 'carnivore');

    async function load(): Promise<void> {
        await refreshAccount();
        if (!signedIn) return;
        try {
            news = await account.readNews();
        } catch {
            news = null;
        }
    }

    $effect(() => {
        void load();
    });

    async function setNews(next: boolean): Promise<void> {
        if (working) return;
        working = true;
        const before = news;
        news = next;
        try {
            news = await account.setNews(next);
            newsNote = null;
        } catch {
            news = before;
            newsNote = t('account.page.news_failed');
        } finally {
            working = false;
        }
    }

    async function signOut(): Promise<void> {
        if (working) return;
        working = true;
        try {
            await host.signOutOfCatalog();
        } finally {
            working = false;
            window.dispatchEvent(new Event(CATALOG_SESSION_EVENT));
        }
    }

    function signIn(): Promise<void> {
        return openSignInModal({ feature: '' as AccountFeature, src: 'account_page' });
    }

    function onDeleted(): void {
        window.dispatchEvent(new Event(CATALOG_SESSION_EVENT));
    }
</script>

<div class="acctpage" data-account-page={signedIn ? 'in' : 'out'}>
    {#if signedIn}
        <section class="acctpage__sec" aria-label={t('account.page.you')}>
            <h2 class="oc-label">{t('account.page.you')}</h2>
            <div class="acctpage__who">
                <Identicon handle={avatarSeed} size={40} />
                <div class="acctpage__lines">
                    {#if handle}
                        <span class="acctpage__handle" data-account-handle>{handle}</span>
                    {:else}
                        <button type="button" class="modal-btn modal-btn-secondary" data-account-pick-handle onclick={() => void openRegisterModal()}>
                            {t('account.page.pick_handle')}
                        </button>
                    {/if}
                    {#if facts?.email}
                        <span class="acctpage__email" data-account-email>{facts.email}</span>
                    {/if}
                    {#if facts?.provider}
                        <span class="acctpage__provider" data-account-provider>
                            {t('account.page.provider', { provider: facts.provider })}
                        </span>
                    {/if}
                </div>
            </div>
        </section>

        <section class="acctpage__sec" aria-label={t('account.page.news')}>
            <h2 class="oc-label">{t('account.page.news')}</h2>
            <Check
                label={t('account.page.news_label')}
                checked={news === true}
                disabled={news === null || working}
                onToggle={(next) => void setNews(next)}
                data-account-news=""
            />
            {#if newsNote}
                <p class="acctpage__note" role="status">{newsNote}</p>
            {/if}
        </section>

        <SessionsPanel {host} {t} />
        <AccountPanel {host} {t} {onDeleted} hasHandle={handle !== ''} />

        <section class="acctpage__sec">
            <button type="button" class="modal-btn modal-btn-secondary" data-account-signout disabled={working} onclick={() => void signOut()}>
                {t('account.page.signout')}
            </button>
        </section>
    {:else if guest}
        <section class="acctpage__sec" aria-label={t('account.guest.title')} data-account-guest>
            <h2 class="oc-label">{t('account.guest.title')}</h2>
            <p class="acctpage__lead">{t('account.guest.lead')}</p>
            <button type="button" class="modal-btn modal-btn-secondary" data-account-signin onclick={() => void signIn()}>
                {t('account.guest.keep')}
            </button>
        </section>
        <AccountPanel {host} {t} {onDeleted} hasHandle={false} guest />
    {:else}
        <section class="acctpage__sec" aria-label={t('account.page.out_title')}>
            <h2 class="oc-label">{t('account.page.out_title')}</h2>
            <p class="acctpage__lead">{t('account.page.out_lead')}</p>
            <ul class="acctpage__benefits" data-account-benefits>
                <li>{t('account.page.benefit_share')}</li>
                <li>{t('account.page.benefit_sync')}</li>
                <li>{t('account.page.benefit_skills')}</li>
            </ul>
            <button type="button" class="modal-btn modal-btn-secondary" data-account-signin onclick={() => void signIn()}>
                {t('account.page.signin')}
            </button>
        </section>
    {/if}
</div>

<style>
    .acctpage {
        --cat-raised: var(--oc-ground-raised);
        --cat-panel: var(--oc-ground-panel);
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
        font-family: var(--font-mono);
    }

    .acctpage__sec {
        display: flex;
        flex-direction: column;
        align-items: flex-start;
        gap: 8px;
        padding: 12px var(--cat-gutter);
        border-bottom: 1px solid var(--oc-line-rule);
    }

    .acctpage__who {
        display: flex;
        align-items: center;
        gap: 12px;
    }

    .acctpage__lines {
        display: flex;
        flex-direction: column;
        gap: 2px;
        min-width: 0;
    }

    .acctpage__handle {
        color: var(--oc-text-primary);
        font-size: 15px;
    }

    .acctpage__email,
    .acctpage__provider,
    .acctpage__lead,
    .acctpage__note {
        margin: 0;
        color: var(--oc-text-secondary);
        font-size: 12px;
        line-height: 1.45;
        overflow-wrap: anywhere;
    }

    .acctpage__benefits {
        margin: 0;
        padding-left: 18px;
        color: var(--oc-text-primary);
        font-size: 12px;
        line-height: 1.6;
    }

    .acctpage :global(.modal-btn) {
        padding: 7px 16px;
        font-size: 13px;
    }
</style>
