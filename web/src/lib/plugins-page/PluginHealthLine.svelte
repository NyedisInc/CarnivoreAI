
<script lang="ts">
    import Button from '../base/Button.svelte';
    import type { Translate } from '../sessions/types';
    import { buttonLabelOf, contractOf, reasonOf, toneOf, wordOf, type HealthRow } from './plugin-health';
    import './plugin-pane.css';

    interface Props {
        row: HealthRow;
        label?: string;
        canAct: boolean;
        onAct: () => void;
        t: Translate;
    }

    const { row, label, canAct, onAct, t }: Props = $props();
    const tone = $derived(toneOf(row));
    const reason = $derived(reasonOf(row, t));
    const button = $derived(canAct ? buttonLabelOf(row, t) : null);
    const contract = $derived(contractOf(row, t));
</script>

<div class="plp-actions" data-plugin-health={row.id} data-health-word={row.word} data-health-reason={row.reason ?? undefined}>
    {#if label}<span class="plp-actions__note">{label}</span>{/if}
    <span class="plp-state" data-tone={tone === 'off' ? undefined : tone}>{wordOf(row, t)}</span>
    {#if reason}<span class="plp-actions__note" data-health-reason-text>{reason}</span>{/if}
    {#if contract}<span class="plp-actions__note plp-dim" data-health-api-version={row.api_version}>{contract}</span>{/if}
    {#if button}<Button size="sm" data-health-button={row.button} onclick={onAct}>{button}</Button>{/if}
</div>
