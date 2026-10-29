
<script lang="ts">
    import { PUBLISH_KEYS } from '../../../../client/js/labels/skill-publish.js';
    import Button from '../base/Button.svelte';
    import { CATALOG_SESSION_EVENT } from '../drawer-hud/catalog-account.svelte';
    import RegisterFields from '../catalog/RegisterFields.svelte';
    import { errorText } from '../catalog/publish';
    import { isUnmappedCode } from './failures';
    import type { PageProps } from './props';
    import './wizard.css';

    const { store, actions, t }: PageProps = $props();

    let typed = $state('');
    let termsTicked = $state(false);
    let ageTicked = $state(false);
    let registering = $state(false);
    let refusal = $state<string | null>(null);

    const account = $derived(store.account);
    const needsHandle = $derived(account !== null && !account.handle);
    const termsCurrent = $derived(
        account !== null && account.terms_accepted !== undefined && account.terms_accepted !== '' && account.terms_accepted === account.terms_version,
    );
    const ready = $derived((termsCurrent || (termsTicked && ageTicked)) && (!needsHandle || typed.trim() !== '') && !registering);

    async function register(): Promise<void> {
        if (!account || !ready) return;
        registering = true;
        refusal = null;
        const body: { terms_version?: string; age_16_plus?: boolean; handle?: string } = termsCurrent ? {} : { terms_version: account.terms_version, age_16_plus: true };
        if (needsHandle) body.handle = typed.trim().toLowerCase();
        const result = await actions.register(body);
        registering = false;
        if (result.ok) {
            window.dispatchEvent(new Event(CATALOG_SESSION_EVENT));
            return;
        }
        refusal = result.code === 'submission_invalid'
            ? t(PUBLISH_KEYS.handleInvalid, { detail: result.detail })
            : (result.code && !isUnmappedCode(result.code) ? errorText({ detail: { code: result.code } }, t) : '') || result.text;
    }
</script>

{#if store.signedIn && account && !account.registered}
    <div class="d-regi" data-pp="RegisterBlock">
        <p class="d-slot__why">{t(needsHandle ? PUBLISH_KEYS.handleLead : PUBLISH_KEYS.handleLeadTerms)}</p>
        <RegisterFields {account} {t} {needsHandle} {termsCurrent} bind:handle={typed} bind:termsTicked bind:ageTicked {refusal} />
        <div class="pp-foot">
            <Button disabled={!ready} onclick={() => void register()}>{registering ? t(PUBLISH_KEYS.handleClaiming) : t(PUBLISH_KEYS.handleClaim)}</Button>
            {#if account.terms_url}
                <a class="d-wiz__terms" href={account.terms_url} target="_blank" rel="noopener noreferrer">{t(PUBLISH_KEYS.registerTermsLink)}</a>
            {/if}
        </div>
    </div>
{/if}
