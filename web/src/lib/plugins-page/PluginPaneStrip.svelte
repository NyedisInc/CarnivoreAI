
<script lang="ts">
    import Check from '../../opscenter/ui/Check.svelte';
    import type { Translate } from '../sessions/types';
    import type { CplugItem } from './cplugs-adapter';
    import { stateTone, stateWord } from './plugin-pane';
    import './plugin-pane.css';

    interface Props {
        plugin: CplugItem;
        busy?: boolean;
        onToggle: (next: boolean) => void;
        t: Translate;
    }

    const { plugin, busy = false, onToggle, t }: Props = $props();
    const tone = $derived(stateTone(plugin));
</script>

<span class="plp-state" data-plugin-state={plugin.state} data-tone={tone === 'off' ? undefined : tone}>{stateWord(plugin, t)}</span>
{#if typeof plugin.enabled === 'boolean'}
    <Check
        role="switch"
        label={t(plugin.enabled ? 'plugins.page.pane.switch.on' : 'plugins.page.pane.switch.off')}
        ariaLabel={plugin.name}
        checked={plugin.enabled === true}
        disabled={busy}
        data-plugin-pane-switch={plugin.cplugId}
        {onToggle}
    />
{/if}
