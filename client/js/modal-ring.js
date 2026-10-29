(function () {
    'use strict';

    var CARD_SELECTOR = '.modal-content, .sidebar-help__lightbox-body';
    var SHEEN_CLASS = 'mg-sheen';

    function attach(card) {
        if (!card || card.nodeType !== 1) return false;
        for (var i = 0; i < card.children.length; i++) {
            if (card.children[i].classList.contains(SHEEN_CLASS)) return false;
        }
        var span = document.createElement('span');
        span.className = SHEEN_CLASS;
        span.setAttribute('aria-hidden', 'true');
        card.appendChild(span);
        return true;
    }

    function sweep(node) {
        if (!node || node.nodeType !== 1) return;
        if (node.matches(CARD_SELECTOR)) attach(node);
        if (node.firstElementChild) {
            var inner = node.querySelectorAll(CARD_SELECTOR);
            for (var i = 0; i < inner.length; i++) attach(inner[i]);
        }
    }

    function start() {
        sweep(document.body);
        new MutationObserver(function (records) {
            for (var i = 0; i < records.length; i++) {
                var added = records[i].addedNodes;
                for (var j = 0; j < added.length; j++) sweep(added[j]);
            }
        }).observe(document.body, { childList: true, subtree: true });
    }

    window.ModalRing = { attach: attach, CARD_SELECTOR: CARD_SELECTOR };
    if (document.body) start();
    else document.addEventListener('DOMContentLoaded', start, { once: true });
})();
