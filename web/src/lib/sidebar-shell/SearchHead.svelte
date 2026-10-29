<!-- a fold chevron -->
<script lang="ts">
    import { t } from '../i18n/index.svelte';
    import '../deepsearch/search-d.css';

    interface Props {
        label: string;
        count: number | null;
        folded: boolean;
        onfold: () => void;
        action?: { label: string; run: () => void; next: string };
    }
    let { label, count, folded, onfold, action }: Props = $props();
</script>

<div class="sd-hd"><button type="button" class="sd-hd__fold" aria-expanded={!folded} aria-label={t(folded ? 'drawer.search.section.open' : 'drawer.search.section.fold', { name: label })} onmousedown={(e) => e.preventDefault()} onclick={onfold}><span class="sd-hd__chev" data-folded={folded ? '1' : undefined}><svg width="8" height="8" viewBox="0 0 8 8" fill="none" stroke="currentColor" aria-hidden="true"><path d="M1.5 3l2.5 2.5L6.5 3" /></svg></span><span class="sd-hd__label">{label}</span>{#if count !== null}<span class="sd-hd__n">{count}</span>{/if}</button>{#if action}<button type="button" class="sd-hd__act" data-search-next={action.next} onmousedown={(e) => e.preventDefault()} onclick={action.run}>{action.label}</button>{/if}</div>
