(function () {
    'use strict';

    var ATTR = 'data-anim-offscreen';
    if (typeof VisibilityObserver !== 'function') return;

    var seen = new WeakSet();
    var observer = new VisibilityObserver(function (entries) {
        var stepped = false;
        for (var i = 0; i < entries.length; i++) {
            var el = entries[i].target;
            if (el.hasAttribute && el.hasAttribute('data-amb')) stepped = true;
            if (el.isConnected === false) { observer.unobserve(el); seen.delete(el); continue; }
            if (entries[i].isIntersecting) el.removeAttribute(ATTR);
            else el.setAttribute(ATTR, '');
        }
        if (stepped) document.dispatchEvent(new Event('carnivore:amb-visibility'));
    });

    function watch(el) {
        if (el && el.nodeType === 1) el = el.closest('[data-anim-host]') || el;
        if (!el || el.nodeType !== 1 || seen.has(el)) return;
        seen.add(el);
        observer.observe(el);
    }

    document.addEventListener('animationstart', function (e) {
        var el = e.target;
        if (!el || el.nodeType !== 1) return;
        var count = getComputedStyle(el, e.pseudoElement || null).animationIterationCount;
        if ((count && count.indexOf('infinite') !== -1) || (e.animationName || '').indexOf('amb-join-') === 0) watch(el);
    }, true);

    if (typeof document.getAnimations === 'function') {
        document.getAnimations().forEach(function (a) {
            var timing = a.effect && a.effect.getComputedTiming && a.effect.getComputedTiming();
            if (timing && timing.iterations === Infinity && a.effect.target) watch(a.effect.target);
        });
    }
})();
