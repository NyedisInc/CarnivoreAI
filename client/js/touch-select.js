/* there is nothing */

(function () {
    'use strict';

    function tr(key, params) {
        var i18n = globalThis.CloudeI18n;
        return i18n && typeof i18n.t === 'function' ? i18n.t(key, params) : key;
    }

    const LONG_PRESS_MS = 500;
    const MOVE_TOLERANCE = 10;
    const MARGIN = 8;

    let state = 'idle';
    let termWrapper = null;
    let term = null;
    let screenEl = null;
    let timer = null;
    let touchId = null;
    let startX = 0;
    let startY = 0;
    let lastX = 0;
    let lastY = 0;
    let copyBtn = null;

    function init(wrapper) {
        const coarse = (window.matchMedia && window.matchMedia('(pointer: coarse)').matches) ||
            ('ontouchstart' in window);
        if (!coarse) return;
        if (!wrapper || !wrapper.term || !wrapper.term.element) return;

        termWrapper = wrapper;
        term = wrapper.term;
        screenEl = term.element.querySelector('.xterm-screen') || term.element;
        const container = term.element.parentElement; // #terminal
        if (!container) return;

        container.addEventListener('touchstart', onTouchStart, { capture: true, passive: true });
        container.addEventListener('touchmove', onTouchMove, { capture: true, passive: false });
        container.addEventListener('touchend', onTouchEnd, { capture: true, passive: false });
        container.addEventListener('touchcancel', onTouchEnd, { capture: true, passive: false });

        container.addEventListener('contextmenu', (e) => {
            if (state !== 'idle') e.preventDefault();
        }, true);

        document.addEventListener('touchstart', onDocTouchStart, { capture: true, passive: true });
    }


    function onTouchStart(e) {
        if (state !== 'idle') return;
        const t = e.changedTouches[0];
        touchId = t.identifier;
        startX = lastX = t.clientX;
        startY = lastY = t.clientY;
        state = 'pending';
        timer = setTimeout(enterSelectMode, LONG_PRESS_MS);
    }

    function onTouchMove(e) {
        if (state === 'idle') return;
        const t = activeTouch(e);
        if (!t) return;

        if (state === 'pending') {
            if (Math.abs(t.clientX - startX) > MOVE_TOLERANCE ||
                Math.abs(t.clientY - startY) > MOVE_TOLERANCE) {
                cancelPending();
                return;
            }
        } else if (state === 'selecting') {
            e.preventDefault();
            e.stopPropagation();
            lastX = t.clientX;
            lastY = t.clientY;
            dispatchMouse('mousemove', t.clientX, t.clientY);
        }
    }

    function onTouchEnd(e) {
        if (state === 'idle') return;
        const t = activeTouch(e);
        if (!t) return;

        if (state === 'pending') {
            cancelPending();
            return;
        }

        e.preventDefault();
        e.stopPropagation();
        lastX = t.clientX;
        lastY = t.clientY;
        dispatchMouse('mouseup', t.clientX, t.clientY);
        state = 'idle';
        touchId = null;

        if (term.hasSelection()) {
            showCopyButton(lastX, lastY);
        } else {
            hidePill();
        }
    }

    function onDocTouchStart(e) {
        if (state === 'idle' && !copyBtn) return;
        if (copyBtn && copyBtn.contains(e.target)) return;
        exitSelectMode(true);
    }

    function activeTouch(e) {
        for (let i = 0; i < e.changedTouches.length; i++) {
            if (e.changedTouches[i].identifier === touchId) return e.changedTouches[i];
        }
        return null;
    }

    function cancelPending() {
        if (timer) { clearTimeout(timer); timer = null; }
        state = 'idle';
        touchId = null;
    }


    function enterSelectMode() {
        timer = null;
        if (state !== 'pending') return;
        state = 'selecting';

        dispatchMouse('mousedown', startX, startY);

        if (term.textarea && document.activeElement === term.textarea) {
            term.textarea.blur();
        }

        termWrapper._showStatusPill('select mode - drag to highlight', 'info');
    }

    function clampToRows(x, y) {
        if (!screenEl || typeof screenEl.getBoundingClientRect !== 'function') {
            return { x: x, y: y };
        }
        const r = screenEl.getBoundingClientRect();
        if (!r || !r.height || !r.width) return { x: x, y: y };
        const rows = (term && term.rows) || 1;
        const pad = Math.max(1, r.height / rows);
        return {
            x: Math.min(Math.max(x, r.left + 1), r.right - 1),
            y: Math.min(Math.max(y, r.top + pad), r.bottom - pad),
        };
    }

    function dispatchMouse(type, x, y) {
        if (!screenEl) return;
        const at = clampToRows(x, y);
        screenEl.dispatchEvent(new MouseEvent(type, {
            bubbles: true,
            cancelable: true,
            view: window,
            button: 0,
            buttons: type === 'mouseup' ? 0 : 1,
            detail: 1,
            clientX: at.x,
            clientY: at.y,
        }));
    }

    function exitSelectMode(clearSel) {
        cancelPending();
        if (clearSel && term && term.hasSelection()) term.clearSelection();
        removeCopyButton();
        hidePill();
    }


    function showCopyButton(x, y) {
        removeCopyButton();
        hidePill();
        copyBtn = document.createElement('button');
        copyBtn.type = 'button';
        copyBtn.className = 'cloude-touch-copy';
        copyBtn.textContent = tr('touch.select.copy');
        document.body.appendChild(copyBtn);

        const vp = window.visualViewport || null;
        const vw = vp ? vp.width : window.innerWidth;
        const vh = vp ? vp.height : window.innerHeight;
        const offL = vp ? vp.offsetLeft : 0;
        const offT = vp ? vp.offsetTop : 0;
        const w = copyBtn.offsetWidth;
        const h = copyBtn.offsetHeight;

        let left = x + MARGIN;
        let top = y - h - MARGIN;
        left = Math.min(Math.max(left, offL + MARGIN), offL + vw - w - MARGIN);
        top = Math.min(Math.max(top, offT + MARGIN), offT + vh - h - MARGIN);
        copyBtn.style.left = left + 'px';
        copyBtn.style.top = top + 'px';

        copyBtn.addEventListener('click', onCopyTap);
    }

    function onCopyTap(e) {
        e.stopPropagation();
        const text = term ? term.getSelection() : '';
        exitSelectMode(true);
        if (!text) {
            termWrapper._showStatusPill('nothing selected', 'info');
            return;
        }
        window.CopyCompat.copyText(text).then((result) => {
            if (result.ok) {
                termWrapper._showStatusPill('copied', 'success');
            } else {
                termWrapper._showStatusPill('copy blocked - use the copy button for a selectable view', 'error');
            }
        });
    }

    function removeCopyButton() {
        if (copyBtn) {
            copyBtn.removeEventListener('click', onCopyTap);
            copyBtn.remove();
            copyBtn = null;
        }
    }

    function hidePill() {
        if (window.FabMenu && typeof window.FabMenu.dismissNotice === 'function') {
            window.FabMenu.dismissNotice();
        }
    }

    function isSelecting() {
        return state === 'selecting';
    }

    window.TouchSelect = { init, isSelecting, clampToRows };
})();
