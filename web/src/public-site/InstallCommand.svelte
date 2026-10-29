<script lang="ts">
    const command = 'curl -fsSL https://carnivore.ai/install.sh | bash';
    let { label = 'or install from terminal' }: { label?: string } = $props();
    let status = $state('');
    let code: HTMLElement | undefined = $state();
    let timer: ReturnType<typeof setTimeout> | undefined;

    function announce(message: string): void {
        status = message;
        clearTimeout(timer);
        timer = setTimeout(() => (status = ''), 2400);
    }

    function selectCommand(): void {
        if (!code) return;
        const range = document.createRange();
        range.selectNodeContents(code);
        const selection = window.getSelection();
        selection?.removeAllRanges();
        selection?.addRange(range);
    }

    async function copy(): Promise<void> {
        try {
            if (!navigator.clipboard) throw new Error('clipboard unavailable');
            await navigator.clipboard.writeText(command);
            announce('copied');
        } catch {
            selectCommand();
            announce('press cmd+c to copy the selected command');
        }
    }
</script>

<div class="install-cmd">
    <p class="install-cmd__label">{label}</p>
    <div class="install-cmd__row tw:flex tw:flex-wrap tw:items-stretch">
        <code class="install-cmd__code" bind:this={code}>{command}</code>
        <button type="button" class="install-cmd__copy" onclick={copy}>{status === 'copied' ? 'copied' : 'copy'}</button>
    </div>
    <span class="sr-only" role="status" aria-live="polite">{status}</span>
</div>
