
<script lang="ts">
    import type { Snippet } from 'svelte';
    import type { Attachment } from 'svelte/attachments';
    import Heading from './Heading.svelte';
    import type { HeadingPlan } from './plan';

    interface Props {
        kind?: string;
        attrs?: Record<string, string | undefined>;
        heading?: HeadingPlan;
        bodyId?: string;
        block?: string;
        gestures?: Attachment<HTMLElement> | null;
        body?: HTMLElement | null;
        children: Snippet;
    }

    let { kind = '', attrs = {}, heading, bodyId, block, gestures = null, body = $bindable(null), children }: Props = $props();

    const cls = $derived(kind ? `session-sidebar-group ${kind}` : 'session-sidebar-group');
    const id = $derived(bodyId ?? heading?.bodyId);
</script>

<div class={cls} role="group" {...attrs} style:--sb-block={block} {@attach gestures}>{#if heading}<Heading h={heading} />{/if}<div class="session-sidebar-group__body" {id} bind:this={body}>{@render children()}</div></div>
