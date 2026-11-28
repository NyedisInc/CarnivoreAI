<script lang="ts">
    import { onMount } from 'svelte';
    import ModalShell from '../dialog-frame/ModalShell.svelte';
    import { t } from '../i18n/index.svelte';
    import StudioScreen from './StudioScreen.svelte';
    import type { StudioOpenOptions } from './types';

    interface Props {
        close: (value: null) => void;
        initialOptions?: StudioOpenOptions;
        onRegisterClose?: (closeFn: () => void) => void;
    }

    const { close, initialOptions, onRegisterClose }: Props = $props();

    onMount(() => {
        onRegisterClose?.(() => close(null));
    });
</script>

<ModalShell
    look="titlerow"
    title={t('plugin_studio.title')}
    closeLabel={t('plugin_studio.close')}
    width="min(1320px, 95vw)"
    height="min(880px, 92vh)"
    fill={true}
    trapFocus={false}
    onCancel={() => close(null)}
    data-plugin-studio-modal="true"
>
    <StudioScreen embedded={true} {initialOptions} onClose={() => close(null)} />
</ModalShell>
