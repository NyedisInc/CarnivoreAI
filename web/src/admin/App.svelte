
<script lang="ts">
    import { loadOnce } from './load-once.svelte.js';
    import Button from '../lib/base/Button.svelte';
    import { AdminApi } from './admin.js';
    import {
        createHost,
        createTokenStore,
        type AdminHost,
    } from './admin-host.svelte.js';
    import { createNotesHost, type NotesHost } from './notes-host.svelte.js';
    import { refusalMessage, whoText } from './admin.js';
    import { t } from './text.js';
    import { ADMIN_KEYS } from '../../../client/js/labels/admin.js';
    import SignIn from './SignIn.svelte';
    import Users from './Users.svelte';
    import Queue from './Queue.svelte';
    import Notes from './Notes.svelte';
    import Moderation from './Moderation.svelte';
    import Audit from './Audit.svelte';
    import System from './System.svelte';
    import Enroll from './Enroll.svelte';
    import Funnel from './Funnel.svelte';
    import { createCommunityHost, type CommunityHost } from './community-host.svelte.js';

    function defaultHosts(): {
        api: AdminApi;
        host: AdminHost;
        notesHost: NotesHost;
        communityHost: CommunityHost;
    } {
        const tokens = createTokenStore(globalThis);
        const api = new AdminApi(
            (input, init) => globalThis.fetch(input, init as RequestInit),
            () => tokens.read(),
        );
        const host = createHost({ api, tokens });
        const notesHost = createNotesHost({
            api,
            onUnauthorized: () => signOutAll(host, notesHost, communityHost),
        });
        const communityHost = createCommunityHost({
            api,
            onUnauthorized: () => signOutAll(host, notesHost, communityHost),
        });
        return { api, host, notesHost, communityHost };
    }

    const fallback = defaultHosts();
    let {
        api = fallback.api,
        host = fallback.host,
        notesHost = fallback.notesHost,
        communityHost = fallback.communityHost,
    }: {
        api?: AdminApi;
        host?: AdminHost;
        notesHost?: NotesHost;
        communityHost?: CommunityHost;
    } = $props();

    function signOutAll(
        host: AdminHost,
        notesHost: NotesHost,
        communityHost: CommunityHost,
    ): void {
        host.signOut();
        notesHost.reset();
        communityHost.reset();
    }

    $effect(() => {
        const scope = globalThis as unknown as {
            location?: { hash?: string };
            addEventListener?: (n: string, f: () => void) => void;
            removeEventListener?: (n: string, f: () => void) => void;
        };
        const apply = () => host.setRoute(scope.location?.hash || '');
        apply();
        scope.addEventListener?.('hashchange', apply);
        return () => scope.removeEventListener?.('hashchange', apply);
    });

    loadOnce(() => true, () => host.adopt());

    const refusalText = $derived(refusalMessage(host.refusal, t));
    const admin = $derived(host.me?.is_admin === true);
</script>

<header class="admin-bar">
    <h1 class="admin-bar__title">{t(ADMIN_KEYS.title)}</h1>
    {#if (host.step === 'signed_in' || host.step === 'enroll') && host.me}
        <p class="admin-bar__who">
            {admin
                ? t(ADMIN_KEYS.sessionSignedIn, { login: whoText(host.me) })
                : t(ADMIN_KEYS.sessionNotAdmin, { login: whoText(host.me) })}
        </p>
        <Button
            size="sm"
            onclick={() => signOutAll(host, notesHost, communityHost)}
        >
            {t(ADMIN_KEYS.sessionSignOut)}
        </Button>
    {/if}
</header>

{#if refusalText}
    <p class="admin-refusal" role="alert">{refusalText}</p>
{/if}

{#if host.step === 'enroll'}
    <Enroll {host} />
{:else if host.step !== 'signed_in'}
    <SignIn {host} />
{:else if !host.me}
    <p class="admin-note">{t(ADMIN_KEYS.loading)}</p>
{:else if !admin}
    <System {host} />
{:else}
    <nav class="admin-nav">
        <a class="admin-nav__link" href="#/queue">{t(ADMIN_KEYS.navQueue)}</a>
        <a class="admin-nav__link" href="#/users">{t(ADMIN_KEYS.navUsers)}</a>
        <a class="admin-nav__link" href="#/notes">{t(ADMIN_KEYS.navNotes)}</a>
        <a class="admin-nav__link" href="#/moderation">{t(ADMIN_KEYS.navModeration)}</a>
        <a class="admin-nav__link" href="#/audit">{t(ADMIN_KEYS.navAudit)}</a>
        <a class="admin-nav__link" href="#/funnel">{t(ADMIN_KEYS.navFunnel)}</a>
        <a class="admin-nav__link" href="#/system">{t(ADMIN_KEYS.navSystem)}</a>
    </nav>
    {#if host.route === 'users'}
        <Users {host} {api} community={communityHost} />
    {:else if host.route === 'notes'}
        <Notes host={notesHost} />
    {:else if host.route === 'moderation'}
        <Moderation host={communityHost} />
    {:else if host.route === 'audit'}
        <Audit host={communityHost} />
    {:else if host.route === 'funnel'}
        <Funnel {api} />
    {:else if host.route === 'system'}
        <System {host} />
    {:else}
        <Queue {host} />
    {/if}
{/if}
