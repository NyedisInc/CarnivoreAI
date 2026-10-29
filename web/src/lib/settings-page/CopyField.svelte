
<script lang="ts">
    import Button from '../base/Button.svelte';
    import { onDestroy } from 'svelte';
    import type { Translate } from '../sessions/types';
    import { copyText } from './mcp-panel/api';

    interface Props {
        value: string;
        t: Translate;
        label?: string;
        valueAttrs?: Record<string, string>;
        buttonAttrs?: Record<string, string>;
    }

    const { value, t, label = '', valueAttrs = {}, buttonAttrs = {} }: Props = $props();

    let state = $state<'idle' | 'copied' | 'failed'>('idle');
    let timer: ReturnType<typeof setTimeout> | null = null;

    onDestroy(() => {
        if (timer !== null) clearTimeout(timer);
    });

    async function copy(): Promise<void> {
        try {
            await copyText(value);
            state = 'copied';
        } catch {
            state = 'failed';
        }
        if (timer !== null) clearTimeout(timer);
        timer = setTimeout(() => (state = 'idle'), 1500);
    }
</script>

<div class="st-copy">
    <code class="st-copy__value" aria-label={label || undefined} {...valueAttrs}>{value}</code>
    <Button size="sm" {...buttonAttrs} onclick={() => void copy()}>
        {state === 'copied' ? t('settings.copy.copied') : state === 'failed' ? t('settings.copy.failed') : t('settings.copy.copy')}
    </Button>
</div>
