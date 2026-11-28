
<script lang="ts">
    import { Button } from '../base';
    import { useRender } from './context';
    import { resolve, type UiNode } from './validate';

    const { node }: { node: Extract<UiNode, { type: 'code' }> } = $props();
    const ctx = useRender();
    const text = $derived(String(resolve(node.value, ctx.data)));
    let copied = $state(false);
    let timer: ReturnType<typeof setTimeout> | null = null;

    $effect(() => () => {
        if (timer) clearTimeout(timer);
    });

    async function copy(): Promise<void> {
        try {
            if (navigator.clipboard?.writeText) {
                await navigator.clipboard.writeText(text);
            } else {
                const ta = document.createElement('textarea');
                ta.value = text;
                ta.setAttribute('readonly', '');
                ta.style.position = 'fixed';
                ta.style.opacity = '0';
                document.body.appendChild(ta);
                ta.select();
                document.execCommand?.('copy');
                ta.remove();
            }
            copied = true;
            if (timer) clearTimeout(timer);
            timer = setTimeout(() => {
                copied = false;
                timer = null;
            }, 1500);
        } catch {
        }
    }
</script>

<div class="cu-code" data-cu="code" data-language={node.language}>
    <div class="cu-code__head">
        {#if node.language}<span class="cu-code__lang">{node.language}</span>{/if}
        <Button size="sm" onclick={copy}>{ctx.t(copied ? 'cplug_ui.copied' : 'cplug_ui.copy')}</Button>
    </div>
    <pre class="cu-code__pre"><code class="cu-code__text">{text}</code></pre>
</div>
