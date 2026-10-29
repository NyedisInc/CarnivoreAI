import { untrack } from 'svelte';

export function loadOnce(ready: () => boolean, load: () => unknown): void {
    let attempted = false;
    $effect(() => {
        if (attempted || !ready()) return;
        attempted = true;
        untrack(() => void load());
    });
}
