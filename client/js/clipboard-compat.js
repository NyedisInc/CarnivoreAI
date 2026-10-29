(function () {
    'use strict';

    function hasAsyncClipboard() {
        return !!(navigator.clipboard && typeof navigator.clipboard.writeText === 'function');
    }

    function makeCopySource(text) {
        var el = document.createElement('div');
        el.setAttribute('aria-hidden', 'true');
        el.setAttribute('contenteditable', 'true');
        el.style.cssText =
            'position:fixed;top:0;left:0;max-width:1px;max-height:1px;' +
            'overflow:hidden;padding:0;border:none;outline:none;' +
            'opacity:0.01;font-size:16px;white-space:pre;' +
            '-webkit-user-select:text;user-select:text;';
        el.appendChild(document.createTextNode(text));
        document.body.appendChild(el);
        return el;
    }

    function selectAll(el) {
        if (typeof el.focus === 'function') {
            try {
                el.focus({ preventScroll: true });
            } catch (err) {
                el.focus();
            }
        }
        var sel = window.getSelection ? window.getSelection() : null;
        if (!sel || typeof document.createRange !== 'function') return '';
        var range = document.createRange();
        range.selectNodeContents(el);
        sel.removeAllRanges();
        sel.addRange(range);
        return sel.toString();
    }

    function writeAndVerify(e, text) {
        var data = e.clipboardData;
        if (!data || typeof data.setData !== 'function') return false;
        try {
            data.setData('text/plain', text);
            if (typeof data.getData !== 'function') return false;
            if (data.getData('text/plain') !== text) return false;
        } catch (err) {
            console.warn('CopyCompat: clipboardData write failed', err);
            return false;
        }
        e.preventDefault();
        return true;
    }

    function copyViaExecCommand(text) {
        var el = makeCopySource(text);
        var fired = false;
        var injected = false;

        function onCopy(e) {
            fired = true;
            injected = writeAndVerify(e, text);
        }

        var reported = false;
        var selected = '';
        document.addEventListener('copy', onCopy, true);
        try {
            selected = selectAll(el);
            reported = document.execCommand('copy');
        } catch (err) {
            console.warn('CopyCompat: execCommand copy threw', err);
            reported = false;
        } finally {
            document.removeEventListener('copy', onCopy, true);
            var sel = window.getSelection ? window.getSelection() : null;
            if (sel) sel.removeAllRanges();
            el.remove();
        }
        var proven = injected || selected === text;
        if (reported && fired && !proven) {
            console.warn('CopyCompat: copy ran unproven, selection held ' +
                selected.length + ' chars, wanted ' + text.length);
        }
        return !!(reported && fired && proven);
    }

    function copyText(text) {
        if (!text) {
            return Promise.resolve({ ok: false, method: 'manual' });
        }

        if (!hasAsyncClipboard()) {
            var did = copyViaExecCommand(text);
            return Promise.resolve({ ok: did, method: did ? 'exec' : 'manual' });
        }

        return navigator.clipboard.writeText(text).then(function () {
            return { ok: true, method: 'async' };
        }).catch(function () {
            var ok = copyViaExecCommand(text);
            return { ok: ok, method: ok ? 'exec' : 'manual' };
        });
    }

    window.CopyCompat = {
        copyText: copyText,
        hasAsyncClipboard: hasAsyncClipboard,
        copyViaExecCommand: copyViaExecCommand
    };
})();
