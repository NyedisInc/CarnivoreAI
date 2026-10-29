<!-- does not verify -->
<script lang="ts">
    import type { Translate } from '../sessions/types';
    import type { CatalogIndexState } from './types';

    interface Props {
        index: CatalogIndexState | null;
        t: Translate;
    }

    const { index, t }: Props = $props();

    const day = (stamp: unknown): string => (typeof stamp === 'string' && stamp ? stamp.slice(0, 10) : '-');
    const keyId = $derived(typeof index?.key_id === 'string' && index.key_id ? index.key_id : null);
</script>

{#if index}
    <p class="trustline" data-trust-line>
        {t('warez.online.trust', { serial: typeof index.serial === 'number' ? String(index.serial) : '-', generated: day(index.generated_at), expires: day(index.expires_at) })}{#if keyId}{' \u00b7 '}{t('warez.online.trust_key', { key: keyId })}{/if}
    </p>
{/if}

<style>
    .trustline {
        flex: none;
        margin: 0;
        padding: var(--oc-space-2) var(--oc-page-gutter, var(--oc-space-4));
        box-shadow: inset 0 1px 0 0 var(--oc-line-faint);
        color: var(--oc-text-muted);
        font-family: var(--font-mono);
        font-size: var(--oc-fs-label);
        overflow-wrap: anywhere;
    }
</style>
