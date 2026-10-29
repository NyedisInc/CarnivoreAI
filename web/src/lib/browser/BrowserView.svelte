<script lang="ts">
    /*  hidden  */
    import { onDestroy } from 'svelte';
    import Icon from '../../opscenter/ui/Icon.svelte';
    import { viewport } from '../../opscenter/engine/viewport.svelte';
    import { t } from '../i18n/index.svelte';
    import { openBrowserSocket, type BrowserSocket, type ConnState, type ServerMessage } from './browser-socket';
    import {
        keyMessage,
        modifiersOf,
        mouseButton,
        pageScale,
        toPagePoint,
        viewportFor,
        wheelDelta,
        type PageSize,
    } from './input-map';

    let {
        browserId,
        compact = false,
        focusAddress = false,
    }: {
        browserId: string;
        compact?: boolean;
        focusAddress?: boolean;
    } = $props();

    let canvas = $state<HTMLCanvasElement | null>(null);
    let stage = $state<HTMLElement | null>(null);
    let ime = $state<HTMLTextAreaElement | null>(null);
    let addressInput = $state<HTMLInputElement | null>(null);

    let conn = $state<ConnState>('connecting');
    let connDetail = $state('');
    let page = $state<PageSize | null>(null);
    let nav = $state({ url: '', title: '', canGoBack: false, canGoForward: false, loading: false });
    let address = $state('');
    let editing = $state(false);
    let notice = $state('');
    let dialog = $state<{ kind: string; message: string; defaultPrompt: string } | null>(null);
    let promptText = $state('');
    let hasFrame = $state(false);

    let socket: BrowserSocket | null = null;
    let pendingNav = '';
    let noticeTimer: ReturnType<typeof setTimeout> | undefined;
    let resizeTimer: ReturnType<typeof setTimeout> | undefined;


    let decoding = false;
    let waiting: Blob | null = null;

    function onFrame(blob: Blob): void {
        waiting = blob;
        if (!decoding) void drain();
    }

    async function drain(): Promise<void> {
        decoding = true;
        while (waiting) {
            const blob = waiting;
            waiting = null;
            try {
                const bitmap = await createImageBitmap(blob);
                if (canvas) {
                    if (canvas.width !== bitmap.width || canvas.height !== bitmap.height) {
                        canvas.width = bitmap.width;
                        canvas.height = bitmap.height;
                    }
                    canvas.getContext('2d')?.drawImage(bitmap, 0, 0);
                    hasFrame = true;
                }
                bitmap.close();
            } catch (err) {
                console.warn('BrowserView: a frame could not be decoded', err);
            }
        }
        decoding = false;
    }


    function say(text: string): void {
        notice = text;
        if (noticeTimer !== undefined) clearTimeout(noticeTimer);
        noticeTimer = setTimeout(() => (notice = ''), 6000);
    }

    function onMessage(message: ServerMessage): void {
        if (message.type === 'meta') page = { width: message.width, height: message.height };
        else if (message.type === 'nav') {
            nav = message;
            if (!editing) address = message.url === 'about:blank' ? '' : message.url;
        } else if (message.type === 'restarted') say(t('browser.restarted'));
        else if (message.type === 'notice') say(message.message);
        else if (message.type === 'dialog') {
            dialog = { kind: message.kind, message: message.message, defaultPrompt: message.defaultPrompt ?? '' };
            promptText = dialog.defaultPrompt;
        }
    }

    function onState(state: ConnState, detail = ''): void {
        conn = state;
        connDetail = detail;
        if (state === 'open') {
            sendResize();
            if (pendingNav) send({ type: 'navigate', url: pendingNav });
            pendingNav = '';
        }
        if (state !== 'open') dialog = null;
    }

    $effect(() => {
        const id = browserId;
        hasFrame = false;
        page = null;
        const opened = openBrowserSocket(id, { onFrame, onMessage, onState });
        socket = opened;
        return () => {
            opened.close();
            if (socket === opened) socket = null;
        };
    });

    function send(message: object): void {
        socket?.send(message);
    }


    function sendResize(): void {
        if (!stage || conn !== 'open') return;
        const box = stage.getBoundingClientRect();
        if (box.width < 1 || box.height < 1) return;
        send({ type: 'resize', ...viewportFor(box.width, box.height, globalThis.devicePixelRatio || 1) });
    }

    $effect(() => {
        const el = stage;
        if (!el || typeof ResizeObserver === 'undefined') return;
        const observer = new ResizeObserver(() => {
            if (resizeTimer !== undefined) clearTimeout(resizeTimer);
            resizeTimer = setTimeout(sendResize, 150);
        });
        observer.observe(el);
        return () => observer.disconnect();
    });

    $effect(() => {
        if (focusAddress && conn === 'open' && nav.url === 'about:blank' && !nav.loading) addressInput?.focus();
    });


    let lastMove = 0;
    let touch: { id: number; x: number; y: number; moved: boolean } | null = null;

    function point(e: { clientX: number; clientY: number }): { x: number; y: number } | null {
        if (!canvas || !page) return null;
        return toPagePoint(e.clientX, e.clientY, canvas.getBoundingClientRect(), page);
    }

    function mouse(event: string, e: PointerEvent | MouseEvent, extra: Record<string, unknown> = {}): void {
        const at = point(e);
        if (!at) return;
        send({
            type: 'mouse',
            event,
            ...at,
            button: mouseButton(e.button),
            buttons: e.buttons & 31,
            clickCount: 0,
            modifiers: modifiersOf(e),
            ...extra,
        });
    }

    function onPointerDown(e: PointerEvent): void {
        canvas?.focus();
        if (e.pointerType === 'touch') {
            touch = { id: e.pointerId, x: e.clientX, y: e.clientY, moved: false };
            return;
        }
        canvas?.setPointerCapture(e.pointerId);
        e.preventDefault();
        mouse('down', e, { clickCount: Math.min(Math.max(e.detail, 1), 3) });
    }

    function onPointerMove(e: PointerEvent): void {
        if (e.pointerType === 'touch') {
            if (!touch || touch.id !== e.pointerId || !canvas || !page) return;
            const dx = touch.x - e.clientX;
            const dy = touch.y - e.clientY;
            if (!touch.moved && Math.hypot(dx, dy) < 8) return;
            touch.moved = true;
            touch.x = e.clientX;
            touch.y = e.clientY;
            const scale = pageScale(canvas.getBoundingClientRect(), page);
            mouse('wheel', e, { button: 'none', buttons: 0, deltaX: Math.round(dx * scale), deltaY: Math.round(dy * scale) });
            return;
        }
        const now = performance.now();
        if (now - lastMove < 16 && e.buttons === 0) return;
        lastMove = now;
        mouse('move', e, { button: 'none' });
    }

    function onPointerUp(e: PointerEvent): void {
        if (e.pointerType === 'touch') {
            const tap = touch && touch.id === e.pointerId && !touch.moved;
            touch = null;
            if (!tap) return;
            mouse('move', e, { button: 'none', buttons: 0 });
            mouse('down', e, { button: 'left', buttons: 1, clickCount: 1 });
            mouse('up', e, { button: 'left', buttons: 0, clickCount: 1 });
            return;
        }
        mouse('up', e, { clickCount: Math.min(Math.max(e.detail, 1), 3) });
    }

    $effect(() => {
        const el = canvas;
        if (!el) return;
        const onWheel = (e: WheelEvent): void => {
            e.preventDefault();
            if (!page) return;
            mouse('wheel', e, { button: 'none', ...wheelDelta(e, page.height) });
        };
        el.addEventListener('wheel', onWheel, { passive: false });
        return () => el.removeEventListener('wheel', onWheel);
    });


    function isClipboard(e: KeyboardEvent): boolean {
        return (e.metaKey || e.ctrlKey) && ['c', 'v', 'x'].includes(e.key.toLowerCase());
    }

    function onKey(e: KeyboardEvent, event: 'down' | 'up'): void {
        if (e.isComposing || isClipboard(e)) return;
        e.preventDefault();
        send(keyMessage(e, event));
    }

    function onPaste(e: ClipboardEvent): void {
        const text = e.clipboardData?.getData('text') ?? '';
        if (!text) return;
        e.preventDefault();
        send({ type: 'text', value: text });
    }

    function onImeInput(e: Event): void {
        if ((e as InputEvent).isComposing || !ime) return;
        if (ime.value) send({ type: 'text', value: ime.value });
        ime.value = '';
    }

    function onImeCompositionEnd(): void {
        if (!ime) return;
        if (ime.value) send({ type: 'text', value: ime.value });
        ime.value = '';
    }

    const EDIT_KEYS = ['Backspace', 'Delete', 'Enter', 'Tab', 'Escape', 'ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight'];

    function onImeKeydown(e: KeyboardEvent): void {
        if (e.isComposing || !EDIT_KEYS.includes(e.key)) return;
        e.preventDefault();
        send(keyMessage(e, 'down'));
        send(keyMessage(e, 'up'));
    }


    function go(e: SubmitEvent): void {
        e.preventDefault();
        const url = address.trim();
        if (!url) return;
        editing = false;
        addressInput?.blur();
        if (conn === 'open') send({ type: 'navigate', url });
        else pendingNav = url;
        canvas?.focus();
    }

    function answer(accept: boolean): void {
        send({ type: 'dialog', accept, promptText });
        dialog = null;
    }

    const stateLine = $derived.by(() => {
        if (conn === 'connecting') return t('browser.state.connecting');
        if (conn === 'stopped') return t('browser.state.stopped', { reason: connDetail });
        if (conn === 'gone') return t('browser.state.gone');
        if (conn === 'refused') return t('browser.state.refused', { detail: connDetail });
        if (conn === 'signed-out') return t('browser.state.signed_out');
        return hasFrame ? '' : t('browser.state.waiting');
    });

    export function currentUrl(): string {
        return nav.url;
    }

    onDestroy(() => {
        if (noticeTimer !== undefined) clearTimeout(noticeTimer);
        if (resizeTimer !== undefined) clearTimeout(resizeTimer);
    });
</script>

<div class="bv" class:bv-compact={compact} data-browser-id={browserId}>
    <form class="bv-bar" onsubmit={go}>
        <button type="button" class="bv-btn" disabled={!nav.canGoBack} aria-label={t('browser.back')} onclick={() => send({ type: 'back' })}>
            <Icon name="back" size={14} />
        </button>
        <button type="button" class="bv-btn" disabled={!nav.canGoForward} aria-label={t('browser.forward')} onclick={() => send({ type: 'forward' })}>
            <Icon name="arrow" size={14} />
        </button>
        {#if nav.loading}
            <button type="button" class="bv-btn" title={t('browser.stop')} aria-label={t('browser.stop')} onclick={() => send({ type: 'stop' })}>
                <Icon name="close" size={14} />
            </button>
        {:else}
            <button type="button" class="bv-btn" aria-label={t('browser.reload')} onclick={() => send({ type: 'reload' })}>
                <Icon name="reset" size={14} />
            </button>
        {/if}
        <input
            bind:this={addressInput}
            bind:value={address}
            class="bv-address"
            type="text"
            inputmode="url"
            autocomplete="off"
            autocapitalize="off"
            spellcheck="false"
            placeholder={t('browser.address.placeholder')}
            title={t('browser.address.where')}
            aria-label={t('browser.address')}
            aria-describedby={editing ? `bv-where-${browserId}` : undefined}
            onfocus={() => (editing = true)}
            onblur={() => (editing = false)}
        />
        {#if viewport.phone}
            <button type="button" class="bv-btn" title={t('browser.keyboard.hint')} aria-label={t('browser.keyboard')} onclick={() => ime?.focus()}>
                <Icon name="keyboard" size={14} />
            </button>
        {/if}
    </form>
    {#if dialog}
        <div class="bv-dialog" role="alertdialog" aria-label={t('browser.dialog')}>
            <span class="bv-dialog-text">{dialog.message}</span>
            {#if dialog.kind === 'prompt'}
                <input class="bv-address" type="text" bind:value={promptText} aria-label={t('browser.dialog.answer')} />
            {/if}
            <button type="button" class="bv-btn bv-word" onclick={() => answer(true)}>{t('browser.dialog.ok')}</button>
            {#if dialog.kind !== 'alert'}
                <button type="button" class="bv-btn bv-word" onclick={() => answer(false)}>{t('browser.dialog.cancel')}</button>
            {/if}
        </div>
    {/if}
    <div class="bv-stage" bind:this={stage}>
        {#if editing}
            
            <p class="bv-where" id={`bv-where-${browserId}`} data-browser-where>{t('browser.address.where')}</p>
        {/if}
        
        <canvas
            bind:this={canvas}
            data-fit-backdrop
            class="bv-canvas"
            tabindex="0"
            aria-label={nav.title || t('browser.page')}
            onpointerdown={onPointerDown}
            onpointermove={onPointerMove}
            onpointerup={onPointerUp}
            onpointercancel={() => (touch = null)}
            oncontextmenu={(e) => e.preventDefault()}
            onkeydown={(e) => onKey(e, 'down')}
            onkeyup={(e) => onKey(e, 'up')}
            onpaste={onPaste}
        ></canvas>
        <textarea
            bind:this={ime}
            class="bv-ime"
            autocomplete="off"
            autocapitalize="off"
            spellcheck="false"
            aria-label={t('browser.keyboard')}
            oninput={onImeInput}
            oncompositionend={onImeCompositionEnd}
            onkeydown={onImeKeydown}
            onpaste={onPaste}
        ></textarea>
        {#if stateLine}
            <div class="bv-state" role="status">
                <span>{stateLine}</span>
                {#if conn === 'stopped' || conn === 'refused'}
                    <button type="button" class="bv-btn bv-word" onclick={() => socket?.reopen()}>{t('browser.reopen')}</button>
                {/if}
            </div>
        {/if}
        {#if notice}
            <div class="bv-notice" role="status">{notice}</div>
        {/if}
    </div>
</div>

<style>
    .bv {
        display: flex;
        flex-direction: column;
        width: 100%;
        height: 100%;
        min-height: 0;
        background: var(--oc-ground-page);
        color: var(--oc-text-primary);
    }

    .bv-bar,
    .bv-dialog {
        display: flex;
        align-items: center;
        gap: 6px;
        padding: 6px 8px;
        background: var(--oc-ground-chrome);
        border-bottom: 1px solid var(--oc-line-panel);
    }

    .bv-compact .bv-bar {
        gap: 4px;
        padding: 3px 4px;
    }

    .bv-btn {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        flex: none;
        min-width: 28px;
        height: 28px;
        padding: 0 6px;
        background: none;
        border: var(--oc-border, 1px) solid var(--oc-line-panel);
        border-radius: var(--oc-radius);
        color: var(--oc-text-secondary);
        font: inherit;
        font-size: 12px;
        cursor: pointer;
    }

    .bv-btn:hover:not(:disabled),
    .bv-btn:focus-visible {
        background: var(--oc-ground-hover);
        color: var(--oc-text-primary);
        outline: none;
    }

    .bv-btn:disabled {
        opacity: 0.4;
        cursor: default;
    }

    .bv-address {
        flex: 1 1 auto;
        min-width: 0;
        height: 28px;
        padding: 0 8px;
        background: var(--oc-ground-page);
        border: var(--oc-border, 1px) solid var(--oc-line-panel);
        border-radius: var(--oc-radius);
        color: var(--oc-text-primary);
        font: inherit;
        font-size: 16px;
    }

    .bv-compact .bv-btn,
    .bv-compact .bv-address {
        height: 24px;
        min-width: 24px;
    }

    .bv-dialog-text {
        flex: 1 1 auto;
        min-width: 0;
        overflow: hidden;
        text-overflow: ellipsis;
        font-size: 12px;
    }

    .bv-stage {
        position: relative;
        flex: 1 1 auto;
        min-height: 0;
        overflow: hidden;
        background: var(--oc-ground-field);
    }

    .bv-canvas {
        display: block;
        width: 100%;
        height: 100%;
        object-fit: contain;
        touch-action: none;
        outline: none;
    }

    .bv-canvas:focus-visible {
        box-shadow: inset 0 0 0 1px var(--oc-line-panel);
    }

    .bv-ime {
        position: absolute;
        left: 0;
        bottom: 0;
        width: 1px;
        height: 1px;
        padding: 0;
        border: 0;
        opacity: 0;
        font-size: 16px;
        resize: none;
    }

    .bv-state,
    .bv-notice {
        position: absolute;
        left: 50%;
        transform: translateX(-50%);
        display: flex;
        align-items: center;
        gap: 8px;
        max-width: calc(100% - 16px);
        padding: 6px 10px;
        background: var(--oc-ground-raised);
        border: var(--oc-border, 1px) solid var(--oc-line-panel);
        border-radius: var(--oc-radius);
        font-size: 12px;
    }

    .bv-state {
        top: 40%;
    }

    .bv-where {
        position: absolute;
        top: 0;
        left: 0;
        right: 0;
        z-index: 1;
        margin: 0;
        padding: 4px 8px;
        background: var(--oc-ground-raised);
        box-shadow: 0 1px 0 var(--oc-line-panel);
        color: var(--oc-text-dim);
        font-size: 12px;
        pointer-events: none;
    }

    .bv-notice {
        bottom: 8px;
    }
</style>
