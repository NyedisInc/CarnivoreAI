
<script lang="ts">
    import type { Translate } from '../sessions/types';
    import type { CplugItem } from '../plugins-page/cplugs-adapter';
    import HostFrame from './HostFrame.svelte';
    import Renderer from './Renderer.svelte';
    import { watchSurface, type SurfaceState } from './surface.svelte';
    import type { Surface } from './api';

    interface Props {
        plugin: Pick<CplugItem, 'cplugId' | 'name' | 'unverified' | 'installKey' | 'declared'>;
        surface: Surface;
        t: Translate;
    }

    const { plugin, surface, t }: Props = $props();
    const declared = $derived(plugin.declared ?? { routes: [], tools: [] });
    let state = $state<SurfaceState>({ kind: 'loading' });

    $effect(() => watchSurface({ cplugId: plugin.cplugId, installKey: plugin.installKey ?? null, surface }, (next) => { state = next; }));

    const line = $derived(
        state.kind === 'stopped' ? 'cplug_ui.not_running'
        : state.kind === 'refused' ? 'cplug_ui.could_not_draw'
        : state.kind === 'none' ? 'cplug_ui.nothing_here'
        : state.kind === 'loading' ? 'cplug_ui.loading'
        : null,
    );
</script>

{#if state.kind === 'ready'}
    <Renderer cplugId={plugin.cplugId} name={plugin.name} unverified={plugin.unverified} document={state.document} {declared} stale={state.stale} {t} />
{:else}
    <HostFrame name={plugin.name} unverified={plugin.unverified} note={line ? t(line) : null} {t} />
{/if}
