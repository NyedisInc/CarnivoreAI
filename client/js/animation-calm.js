(function () {
    'use strict';

    var ATTR = 'data-anim-calm';
    var root = document.documentElement;
    var PSEUDO = { '::before': 'before', '::after': 'after' };
    var listening = false;

    function isCalm() { return root.getAttribute('data-calm') !== null; }

    function mark(el, token) {
        var cur = el.getAttribute(ATTR);
        var tokens = cur ? cur.split(' ') : [];
        if (tokens.indexOf(token) === -1) { tokens.push(token); el.setAttribute(ATTR, tokens.join(' ')); }
    }

    function onStart(e) {
        var el = e.target;
        if (!el || el.nodeType !== 1) return;
        var token = e.pseudoElement ? PSEUDO[e.pseudoElement] : 'self';
        if (!token) return;
        var count = getComputedStyle(el, e.pseudoElement || null).animationIterationCount;
        if (count && count.indexOf('infinite') !== -1) mark(el, token);
    }

    function enter() {
        var want = new Map();
        var anims = typeof document.getAnimations === 'function' ? document.getAnimations() : [];
        anims.forEach(function (a) {
            var fx = a.effect;
            var timing = fx && fx.getComputedTiming && fx.getComputedTiming();
            if (!timing || timing.iterations !== Infinity || !fx.target) return;
            var token = fx.pseudoElement ? PSEUDO[fx.pseudoElement] : 'self';
            if (!token) return;
            var set = want.get(fx.target) || want.set(fx.target, new Set()).get(fx.target);
            set.add(token);
        });
        document.querySelectorAll('[' + ATTR + ']').forEach(function (el) { if (!want.has(el)) el.removeAttribute(ATTR); });
        want.forEach(function (set, el) {
            var next = ['self', 'before', 'after'].filter(function (t) { return set.has(t); }).join(' ');
            if (el.getAttribute(ATTR) !== next) el.setAttribute(ATTR, next);
        });
        if (!listening) { document.addEventListener('animationstart', onStart, true); listening = true; }
    }

    function exit() {
        if (listening) { document.removeEventListener('animationstart', onStart, true); listening = false; }
    }

    document.addEventListener('carnivore:calm', function (e) {
        if (e && e.detail && e.detail.calm) enter(); else exit();
    });
    if (isCalm()) enter();
})();
