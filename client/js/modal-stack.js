/* one thing at a time on a phone */

console.log('[ModalStack Module] Loading...');

(function () {
    const BODY_LOCK_CLASS = 'modal-stack-locked';

    const COVERED_CLASS = 'modal-stack--covered';

    const BASE_Z = 9990;

    const MAX_Z = 9998;

    const stack = [];

    const FOCUSABLE = [
        'a[href]',
        'button:not([disabled])',
        'input:not([disabled])',
        'select:not([disabled])',
        'textarea:not([disabled])',
        '[tabindex]:not([tabindex="-1"])',
    ].join(',');

    const traps = [];

    function restack() {
        stack.forEach((entry, index) => {
            entry.overlayEl.style.zIndex = String(Math.min(BASE_Z + index * 2, MAX_Z));
            const covered = index < stack.length - 1;
            entry.overlayEl.classList.toggle(COVERED_CLASS, covered);
            entry.overlayEl.setAttribute('aria-hidden', covered ? 'true' : 'false');
            if (covered) {
                entry.overlayEl.setAttribute('inert', '');
            } else {
                entry.overlayEl.removeAttribute('inert');
            }
        });
        document.body.classList.toggle(BODY_LOCK_CLASS, stack.length > 0);
    }

    function topIsOutermost() {
        if (stack.length === 0) return false;
        const overlays = document.body.querySelectorAll(':scope > .modal-overlay');
        if (overlays.length === 0) return false;
        return overlays[overlays.length - 1] === stack[stack.length - 1].overlayEl;
    }

    function stops(overlayEl) {
        if (!overlayEl || typeof overlayEl.querySelectorAll !== 'function') return [];
        return Array.prototype.slice.call(overlayEl.querySelectorAll(FOCUSABLE));
    }

    function routeTab(e, entry) {
        const ring = stops(entry.overlayEl);
        if (ring.length === 0) {
            e.preventDefault();
            return;
        }
        const first = ring[0];
        const last = ring[ring.length - 1];
        const active = document.activeElement;
        const inside = !!(active && typeof entry.overlayEl.contains === 'function'
            && entry.overlayEl.contains(active));
        if (e.shiftKey && (active === first || !inside)) {
            e.preventDefault();
            last.focus();
            return;
        }
        if (!e.shiftKey && (active === last || !inside)) {
            e.preventDefault();
            first.focus();
        }
    }

    function onKeydown(e) {
        if (traps.length > 0) {
            const top = traps[traps.length - 1];
            if (e.key === 'Tab') {
                routeTab(e, top);
                return;
            }
            if (e.key !== 'Escape') return;
            e.stopPropagation();
            e.preventDefault();
            if (!top.onEscape) return;
            try {
                top.onEscape();
            } catch (err) {
                console.error('ModalStack: escape handler threw:', err);
            }
            return;
        }
        if (e.key !== 'Escape') return;
        if (stack.length === 0) return;
        if (!topIsOutermost()) return;
        e.stopPropagation();
        e.preventDefault();
        const top = stack[stack.length - 1];
        try {
            top.onEscape();
        } catch (err) {
            console.error('ModalStack: escape handler threw:', err);
        }
    }

    document.addEventListener('keydown', onKeydown, true);

    function push(overlayEl, options) {
        if (!overlayEl || !options || typeof options.onEscape !== 'function') {
            throw new TypeError('ModalStack.push requires an element and an onEscape function');
        }
        if (stack.some((entry) => entry.overlayEl === overlayEl)) return;
        const active = document.activeElement;
        const previousFocus = active && typeof active.focus === 'function' ? active : null;
        stack.push({ overlayEl, onEscape: options.onEscape, previousFocus });
        restack();
    }

    function pop(overlayEl) {
        const index = stack.findIndex((entry) => entry.overlayEl === overlayEl);
        if (index === -1) return;
        const [entry] = stack.splice(index, 1);
        restack();
        const target = entry.previousFocus;
        if (target && document.contains(target)) {
            try { target.focus(); } catch (_) {  }
        }
    }

    function trap(overlayEl, options) {
        if (!overlayEl) {
            throw new TypeError('ModalStack.trap requires an element');
        }
        const opts = options || {};
        const active = document.activeElement;
        const entry = {
            overlayEl,
            onEscape: typeof opts.onEscape === 'function' ? opts.onEscape : null,
            previousFocus: active && typeof active.focus === 'function' ? active : null,
        };
        traps.push(entry);
        const alreadyInside = typeof overlayEl.contains === 'function'
            && overlayEl.contains(document.activeElement);
        if (!alreadyInside) {
            let target = stops(overlayEl)[0];
            if (!target) {
                if (typeof overlayEl.hasAttribute === 'function'
                    && !overlayEl.hasAttribute('tabindex')) {
                    overlayEl.setAttribute('tabindex', '-1');
                }
                target = overlayEl;
            }
            if (target && typeof target.focus === 'function') {
                try { target.focus(); } catch (_) {  }
            }
        }
        let released = false;
        return function release() {
            if (released) return;
            released = true;
            const index = traps.indexOf(entry);
            if (index !== -1) traps.splice(index, 1);
            const back = entry.previousFocus;
            if (back && document.contains(back) && typeof back.focus === 'function') {
                try { back.focus(); } catch (_) {  }
            }
        };
    }

    function trapDepth() {
        return traps.length;
    }

    function depth() {
        return stack.length;
    }

    function isTop(overlayEl) {
        return stack.length > 0 && stack[stack.length - 1].overlayEl === overlayEl;
    }

    window.ModalStack = {
        push, pop, trap, depth, trapDepth, isTop, BODY_LOCK_CLASS, COVERED_CLASS,
    };
    console.log('[ModalStack Module] Exported as window.ModalStack');
})();
