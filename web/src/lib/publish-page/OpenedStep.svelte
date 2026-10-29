
<script lang="ts">
    import type { Snippet } from 'svelte';
    import Button from '../base/Button.svelte';
    import Icon from '../../opscenter/ui/Icon.svelte';
    import type { Translate } from '../sessions/types';
    import './detail.css';
    import type { PageStore } from './page-store.svelte';

    interface Props {
        store: PageStore;
        t: Translate;
        name: string;
        children: Snippet;
    }
    const { store, t, name, children }: Props = $props();
</script>

<div class="pp-opened" data-pp="OpenedStep">
    <div class="d-back"><Button onclick={() => store.closeEvent()}><Icon name="arrow-left" size={14} /> {t('publish.page.view.back_to', { name })}</Button></div>
    {@render children()}
</div>
