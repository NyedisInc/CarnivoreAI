<script lang="ts">
    import { onMount } from 'svelte';
    import { loadCodeMirror, type CodeEditor } from './codemirror';

    let {
        text,
        path,
        readOnly = false,
        onChange,
        onUnavailable,
    }: {
        text: string;
        path: string;
        readOnly?: boolean;
        onChange: (value: string) => void;
        onUnavailable?: (detail: string) => void;
    } = $props();

    let host: HTMLDivElement | undefined = $state();
    let editor: CodeEditor | null = null;

    onMount(() => {
        let live = true;
        const start = { text, path, readOnly };
        loadCodeMirror().then(
            (cm) => {
                if (!live || !host) return;
                editor = cm.createEditor(host, start.text, start.path, start.readOnly, (value) => onChange(value));
            },
            (err: unknown) => {
                console.error('open files: the editor could not be loaded', err);
                if (live) onUnavailable?.(err instanceof Error ? err.message : String(err));
            },
        );
        return () => {
            live = false;
            editor?.destroy();
            editor = null;
        };
    });

    export function focus(): void {
        editor?.focus();
    }
</script>

<div class="config-editor-cm-host" data-readonly={readOnly ? '1' : undefined} data-file-editor="" bind:this={host}></div>

