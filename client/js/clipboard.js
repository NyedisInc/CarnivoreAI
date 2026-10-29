
(function () {
    'use strict';


    /* nothing at all */
    function report(term, message, kind) {
        if (window.FabMenu && typeof window.FabMenu.notify === 'function') {
            window.FabMenu.notify(message, kind);
            return;
        }
        if (term && typeof term._showStatusPill === 'function') {
            term._showStatusPill(message, kind);
        }
    }


    function handleCopyChord(ev, term) {
        if (ev.type !== 'keydown') return false;
        if ((ev.key || '').toLowerCase() !== 'c') return false;

        const isCopyChord =
            (ev.metaKey && !ev.ctrlKey && !ev.shiftKey && !ev.altKey) ||
            (ev.ctrlKey && ev.shiftKey && !ev.metaKey && !ev.altKey);
        if (!isCopyChord) return false;

        if (!term.term || typeof term.term.hasSelection !== 'function' || !term.term.hasSelection()) {
            return false;
        }

        ev.preventDefault();
        ev.stopPropagation();
        writeSystemClipboard(term, term.term.getSelection());
        return true;
    }

    function writeSystemClipboard(term, text) {
        if (!text) return;
        window.CopyCompat.copyText(text).then((result) => {
            if (!result.ok) {
                report(term, 'copy blocked by browser - use the system copy shortcut', 'error');
            }
        });
    }


    /*  hidden  */
    function wireFileInput(term, input) {
        if (!input || input._clipboardWired) return;
        input._clipboardWired = true;
        input.addEventListener('change', async () => {
            const file = input.files && input.files[0];
            if (!file) return;
            const ticket = window.TerminalInputOwnership
                ? window.TerminalInputOwnership.claim('upload') : null;
            await uploadAndInject(term, file, file.name || '', ticket);
            input.value = '';
        });
    }


    async function uploadAndInject(term, blob, filename, ticket) {
        report(term, window.CloudeI18n.t('terminal.upload.progress'), 'info');
        try {
            const sessionId = typeof term._sessionId === 'function' ? term._sessionId() : null;
            const result = await window.API.uploadFile(blob, filename || '', sessionId);
            if (window.TerminalInputOwnership
                && !window.TerminalInputOwnership.deliver(term, ticket)) return;
            term.insertText(quotePathForPrompt(result.path) + ' ');
            if (window.AttachmentToast
                && typeof window.AttachmentToast.show === 'function') {
                window.AttachmentToast.show(term, {
                    blob: blob,
                    filename: result.filename,
                });
            } else {
                report(term, window.CloudeI18n.t('terminal.upload.attached', { name: result.filename }), 'success');
            }
        } catch (err) {
            console.error('[FILE-PASTE] upload failed', err);
            const reason = err && typeof err.message === 'string' && err.message
                ? err.message : window.CloudeI18n.t('terminal.upload.reason_unknown');
            report(term, window.CloudeI18n.t('terminal.upload.failed', { reason }), 'error');
        }
    }

    function quotePathForPrompt(p) {
        var s = String(p == null ? '' : p);
        if (s === '') return s;
        if (/^[A-Za-z0-9._\-\/~+=:,@]+$/.test(s)) return s;
        return "'" + s.split("'").join("'\\''") + "'";
    }


    async function pasteFromClipboard(term, ticket) {
        const own = ticket || (window.TerminalInputOwnership
            ? window.TerminalInputOwnership.claim('paste') : null);
        const canRead = !!(navigator.clipboard && typeof navigator.clipboard.read === 'function');
        const canReadText = !!(navigator.clipboard && typeof navigator.clipboard.readText === 'function');

        if (!canRead && !canReadText) {
            openFallback(term, own);
            return;
        }

        if (canRead) {
            try {
                const items = await navigator.clipboard.read();
                for (const item of items) {
                    const imageType = (item.types || []).find((t) => t.indexOf('image/') === 0);
                    if (imageType) {
                        const blob = await item.getType(imageType);
                        await uploadAndInject(term, blob, '', own);
                        return;
                    }
                }
                for (const item of items) {
                    if ((item.types || []).indexOf('text/plain') !== -1) {
                        const blob = await item.getType('text/plain');
                        injectText(term, await blob.text(), own);
                        return;
                    }
                }
                report(term, 'clipboard is empty', 'info');
                return;
            } catch (err) {
                // Permission denied
            }
        }

        if (canReadText) {
            try {
                const text = await navigator.clipboard.readText();
                if (text) {
                    injectText(term, text, own);
                } else {
                    report(term, 'clipboard is empty', 'info');
                }
                return;
            } catch (err) {
                // Permission denied
            }
        }

        openFallback(term, own);
    }

    function openFallback(term, ticket) {
        if (window.PasteFallback && typeof window.PasteFallback.open === 'function') {
            window.PasteFallback.open(term, injectText, ticket);
            return;
        }
        report(term,
            'paste unavailable on this connection - use cmd+v / ctrl+v in the terminal',
            'error');
    }

    /* at the gesture */
    function injectText(term, text, ticket) {
        if (window.TerminalInputOwnership
            && !window.TerminalInputOwnership.deliver(term, ticket)) return;
        if (!text) {
            report(term, 'clipboard is empty', 'info');
            return;
        }
        if (!term.ws || term.ws.readyState !== WebSocket.OPEN) {
            report(term, 'terminal not connected', 'error');
            return;
        }
        term.insertText(text);
        report(term, 'pasted from clipboard', 'success');
    }

    window.ClipboardTools = {
        handleCopyChord,
        pasteFromClipboard,
        wireFileInput,
        injectText,
        quotePathForPrompt,
        uploadAndInject,
    };
})();
