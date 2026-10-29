
<script lang="ts">
    import { t } from '../i18n/index.svelte';
    import type { LivePart } from './row-body';
    import RowChip from './RowChip.svelte';

    let { parts, none }: { parts: LivePart[]; none: boolean } = $props();
</script>

<span class="session-row-live">{#each parts as part (part.kind)}<RowChip chip={{ attrs: part.attrs, svg: part.svg }}>{#if part.count}<span class="session-row-live__count">{part.count}</span>{/if}{#if part.unit}<span class="session-row-live__unit">{part.unit}</span>{/if}</RowChip>{/each}{#if none && !parts.length}<span class="session-row-live__none">{t('sidebar.row.live.none')}</span>{/if}</span>
