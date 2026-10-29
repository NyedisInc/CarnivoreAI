
<script lang="ts">
    import {
        cancelHeadingRename, commitHeadingRename, headingRename, labelMax,
    } from './heading-rename.svelte';

    let input: HTMLInputElement | undefined = $state();

    function keepCaret(): void {
        if (input) headingRename.caret = [input.selectionStart ?? 0, input.selectionEnd ?? 0];
    }

    function onKeydown(e: KeyboardEvent): void {
        e.stopPropagation();
        if (e.key === 'Enter') {
            e.preventDefault();
            void commitHeadingRename();
            return;
        }
        if (e.key === 'Escape') {
            e.preventDefault();
            cancelHeadingRename();
        }
    }

    function onKeyup(e: KeyboardEvent): void {
        e.stopPropagation();
        keepCaret();
        if (e.key === ' ') e.preventDefault();
    }

    function onBlur(): void {
        const el = input;
        queueMicrotask(() => {
            if (el && el.isConnected) void commitHeadingRename();
        });
    }

    const keys = (node: HTMLInputElement) => {
        node.addEventListener('keydown', onKeydown);
        node.addEventListener('keyup', onKeyup);
        return () => {
            node.removeEventListener('keydown', onKeydown);
            node.removeEventListener('keyup', onKeyup);
        };
    };

    $effect(() => {
        if (!input) return;
        input.focus();
        const caret = headingRename.caret;
        if (caret) input.setSelectionRange(caret[0], caret[1]);
    });

    const selectAllAtMount = headingRename.selectAll;

    $effect(() => {
        if (headingRename.selectAll !== selectAllAtMount && input) {
            input.focus();
            input.select();
            keepCaret();
        }
    });
</script>

<span class="session-sidebar-rename-edit"><input type="text" class="oc-field session-sidebar-rename-input" aria-label={headingRename.spec?.ariaLabel ?? ''} maxlength={labelMax()} bind:this={input} bind:value={headingRename.value} {@attach keys} onblur={onBlur} oninput={keepCaret} onselect={keepCaret} onmouseup={keepCaret} /><span class="session-sidebar-rename-error" hidden={!headingRename.error} role="alert">{headingRename.error}</span></span>
