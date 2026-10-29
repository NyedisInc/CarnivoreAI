
console.log('[DismissGuard Module] Loading...');

(function () {
    'use strict';

    var INTERACTIVE_SELECTOR = [
        'input',
        'textarea',
        'select',
        'button',
        'a[href]',
        'label',
        'option',
        '[contenteditable=""]',
        '[contenteditable="true"]',
        '[role="textbox"]',
        '[role="searchbox"]',
        '[role="combobox"]',
        '[tabindex]:not([tabindex="-1"])',
        '[data-keep-open]'
    ].join(',');

    function isSelfTarget(event, container) {
        if (!event || !container) return false;
        return event.target === container;
    }

    function isInteractiveTarget(event, container) {
        var node = event && event.target;
        if (!node || !container) return false;
        if (typeof node.closest !== 'function') return false;
        var hit = node.closest(INTERACTIVE_SELECTOR);
        return !!(hit && container.contains(hit));
    }

    function onOverlayDismiss(overlayEl, onDismiss) {
        if (!overlayEl || typeof onDismiss !== 'function') return;
        overlayEl.addEventListener('click', function (e) {
            if (!isSelfTarget(e, overlayEl)) return;
            onDismiss(e);
        });
    }

    function onContainerActivate(containerEl, onActivate) {
        if (!containerEl || typeof onActivate !== 'function') return;
        containerEl.addEventListener('click', function (e) {
            if (isInteractiveTarget(e, containerEl)) return;
            onActivate(e);
        });
    }

    function onOutsideDismiss(panelEl, onDismiss, options) {
        if (!panelEl || typeof onDismiss !== 'function') return function () {};
        var opts = options || {};
        var handler = function (e) {
            if (typeof opts.isOpen === 'function' && !opts.isOpen()) return;
            if (panelEl.contains(e.target)) return;
            if (opts.trigger && opts.trigger.contains(e.target)) return;
            onDismiss(e);
        };
        document.addEventListener('click', handler);
        return function () { document.removeEventListener('click', handler); };
    }

    window.DismissGuard = {
        INTERACTIVE_SELECTOR: INTERACTIVE_SELECTOR,
        isSelfTarget: isSelfTarget,
        isInteractiveTarget: isInteractiveTarget,
        onOverlayDismiss: onOverlayDismiss,
        onContainerActivate: onContainerActivate,
        onOutsideDismiss: onOutsideDismiss
    };
})();

console.log('[DismissGuard Module] Exported as window.DismissGuard');
