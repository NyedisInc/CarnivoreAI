
<script lang="ts">
    interface Props {
        hint: string;
        showBack: boolean;
        backLabel: string;
        onBack: () => void;
    }

    const { hint, showBack, backLabel, onBack }: Props = $props();

    let stage = $state<HTMLElement | null>(null);
    let dial = $state<HTMLElement | null>(null);
    let splash = $state<HTMLElement | null>(null);

    export function elements(): { stage: HTMLElement; dial: HTMLElement; splash: HTMLElement } {
        return { stage: stage as HTMLElement, dial: dial as HTMLElement, splash: splash as HTMLElement };
    }
</script>

<div class="elite-stage" hidden bind:this={stage}>
    <div class="boot">
        <pre class="boot-dial" aria-hidden="true" bind:this={dial}></pre>
        <div class="boot-splash" hidden bind:this={splash}></div>
        {#if showBack}<button type="button" class="boot-back" onclick={onBack}>{backLabel}</button>{/if}
        <div class="boot-skip">{hint}</div>
    </div>
</div>
