
<script lang="ts">
    import { untrack } from 'svelte';
    import { PUBLISH_KEYS } from '../../../../client/js/labels/skill-publish.js';
    import type { Translate } from '../sessions/types';
    import { suggestHandle } from './handle-slug';
    import type { PublishAccount } from './publish';

    interface Props {
        account: PublishAccount;
        t: Translate;
        needsHandle: boolean;
        termsCurrent: boolean;
        handle: string;
        termsTicked: boolean;
        ageTicked: boolean;
        refusal: string | null;
    }

    let {
        account,
        t,
        needsHandle,
        termsCurrent,
        handle = $bindable(),
        termsTicked = $bindable(),
        ageTicked = $bindable(),
        refusal,
    }: Props = $props();

    let edited = false;

    $effect(() => {
        const suggestion = suggestHandle(account.provider, account.login);
        if (needsHandle && suggestion && !untrack(() => edited) && untrack(() => handle) === '') {
            handle = suggestion;
        }
    });
</script>

{#if needsHandle}
    <div class="fields__row">
        <label class="modal-label" for="catalog-publish-handle">{t(PUBLISH_KEYS.handleLabel)}</label>
        <input
            type="text"
            class="modal-input"
            id="catalog-publish-handle"
            placeholder={t(PUBLISH_KEYS.handlePlaceholder)}
            autocomplete="off"
            spellcheck="false"
            bind:value={handle}
            oninput={() => (edited = true)}
        />
    </div>
{/if}
{#if refusal}
    <p class="fields__note fields__note--out handle__note--out" role="status">{refusal}</p>
{/if}
{#if !termsCurrent}
    <label class="fields__tick">
        <input type="checkbox" id="catalog-register-terms" bind:checked={termsTicked} />
        <span>{t(PUBLISH_KEYS.registerTerms, { version: account.terms_version })}</span>
    </label>
    <label class="fields__tick">
        <input type="checkbox" id="catalog-register-age" bind:checked={ageTicked} />
        <span>{t(PUBLISH_KEYS.registerAge)}</span>
    </label>
{/if}

<style>
  @layer components {
    .fields__row {
        display: flex;
        align-items: center;
        gap: 8px;
        margin-top: 6px;
    }

    .fields__note {
        margin: 4px 0 0;
        color: var(--oc-text-secondary);
        font-size: 11px;
        line-height: 1.45;
        overflow-wrap: anywhere;
    }

    .fields__note--out {
        padding: 6px 8px;
        border-left: 2px solid var(--oc-yellow);
        background: var(--oc-ground-field);
        color: var(--oc-text-primary);
    }

    .fields__tick {
        display: flex;
        align-items: center;
        gap: 6px;
        margin-top: 6px;
        color: var(--oc-text-secondary);
        font-family: var(--font-mono);
        font-size: 11px;
    }
  }
</style>
