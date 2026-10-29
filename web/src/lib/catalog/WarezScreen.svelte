
<script lang="ts">
    import { onMount } from 'svelte';
    import { t as appT } from '../i18n/index.svelte';
    import { resourcePush } from '../resource-push/boot';
    import type { Translate } from '../sessions/types';
    import CatalogScreen from './CatalogScreen.svelte';
    import type { CatalogHost } from './catalog';
    import type { MenuNode } from './menu/route';

    interface Props {
        host?: CatalogHost;
        t?: Translate;
    }

    const { host, t = appT }: Props = $props();

    const TOPIC = 'catalog';
    const POLL_MS = 60_000;

    let screen = $state<{
        show: (options?: { kind?: string; item?: string; node?: MenuNode; home?: boolean }) => void;
        close: () => void;
        isOpen: () => boolean;
        refresh: () => void;
    } | null>(null);

    const screenProps = $derived(host ? { host } : {});

    export function show(options: { kind?: string; item?: string; node?: MenuNode; home?: boolean } = {}): void {
        screen?.show(options);
    }

    export function close(): void {
        screen?.close();
    }

    export function isOpen(): boolean {
        return screen?.isOpen() ?? false;
    }

    onMount(() => resourcePush().pushOrPoll(() => { if (screen?.isOpen()) screen.refresh(); }, POLL_MS, [TOPIC]));
</script>

<CatalogScreen bind:this={screen} title={t('warez.title')} {t} bands {...screenProps} />
