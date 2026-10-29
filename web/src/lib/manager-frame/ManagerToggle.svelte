
<script lang="ts">
    import type { Translate } from '../sessions/types';
    import Check from '../../opscenter/ui/Check.svelte';
    import { MANAGER_KEYS } from './manager-model';

    interface Props {
        name: string;
        enabled: boolean;
        busy: boolean;
        t: Translate;
        onToggle: (next: boolean) => void;
    }

    const { name, enabled, busy, t, onToggle }: Props = $props();

    const word = $derived(
        busy
            ? t(MANAGER_KEYS.toggleWorking)
            : t(enabled ? MANAGER_KEYS.toggleOn : MANAGER_KEYS.toggleOff),
    );
</script>

<Check
    role="switch"
    label={word}
    checked={enabled}
    disabled={busy}
    ariaLabel={t(MANAGER_KEYS.toggleLabel, { name })}
    onToggle={onToggle}
/>
