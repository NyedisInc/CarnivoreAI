
<script lang="ts">
    import Field from '../base/Field.svelte';
    import Fold from '../base/Fold.svelte';
    import type { Translate } from '../sessions/types';
    import { LEDGER_KEYS } from './ledger-model';
    import { pathHelpKey, pathLabelKey, type ProviderKind } from './accounts-model';

    interface Props {
        open: boolean;
        provider: ProviderKind;
        path: string;
        busy: boolean;
        t: Translate;
    }

    let {
        open = $bindable(),
        provider,
        path = $bindable(),
        busy,
        t,
    }: Props = $props();
</script>

<div data-ledger="advanced">
    <Fold label={t(LEDGER_KEYS.editorAdvanced)} bind:open>
        {#snippet children()}
            
            <Field
                id="ledger-account-path"
                label={t(pathLabelKey(provider))}
                autocomplete="off"
                spellcheck={false}
                disabled={busy}
                bind:value={path}
            />

            <p class="ledger-advanced__help">{t(pathHelpKey(provider))}</p>
        {/snippet}
    </Fold>
</div>

<style>
    .ledger-advanced__help {
        margin: var(--oc-space-1-5) 0 0;
        color: var(--oc-text-secondary);
        font-size: var(--oc-fs-hint);
        line-height: 1.45;
        overflow-wrap: anywhere;
    }
</style>
