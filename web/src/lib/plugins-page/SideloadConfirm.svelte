
<script lang="ts">
    import Button from '../base/Button.svelte';
    import ModalShell from '../dialog-frame/ModalShell.svelte';
    import type { Translate } from '../sessions/types';
    import './plugin-pane.css';

    interface Props {
        t: Translate;
        close: (value: boolean | null) => void;
    }

    const { t, close }: Props = $props();
</script>

<ModalShell look="titlerow" title={t('plugins.page.sideload.confirm.label')} overlayClass="na-flow" onCancel={() => close(null)} data-sideload-confirm="">
    <p class="plp-warn plp-danger" role="alert" data-sideload-risk>{t('plugins.page.sideload.warning.risk')}</p>
    {#snippet footer()}
        <Button size="sm" data-sideload-confirm-cancel="" onclick={() => close(null)}>{t('plugins.page.sideload.cancel')}</Button>
        <Button size="sm" variant="danger" data-sideload-confirm-go="" onclick={() => close(true)}>{t('plugins.page.sideload.confirm.go')}</Button>
    {/snippet}
</ModalShell>
