(function () {
    'use strict';

    var STEP_MS = 250;
    var VAR = '--amb-step';
    var JOIN = 'amb-join-';
    var root = document.documentElement;
    var Motion = window.Motion;
    if (!Motion) return;

    var COVERS = 'body.menu-page-open > .screen, body.menu-page-open > .header, body.menu-page-open #session-notes-panel, ' +
        'body.menu-page-open .config-editor-picker-overlay, .oc-tabpane-hidden, .oc-tf-measure, [data-parked-terminals]';
    var COVERED = ':is(' + COVERS + ') *';

    var wearers = new Map();
    var step = 0;
    var timer = null;
    var coverObserver = null;
    var covered = false;

    function frozen() {
        return root.getAttribute('data-calm') !== null || document.hidden === true || root.hasAttribute('data-oc-still');
    }

    function paint() {
        var need = false;
        covered = false;
        wearers.forEach(function (type, el) {
            if (!el.isConnected) { wearers.delete(el); return; }
            if (Motion.reduced() || Motion.typeOff(type)) { el.style.removeProperty(VAR); return; }
            if (el.hasAttribute('data-anim-offscreen')) return;
            if (el.matches(COVERED)) { covered = true; return; }
            el.style.setProperty(VAR, String(step));
            need = true;
        });
        return need;
    }

    function tick() {
        step += 1;
        if (!paint()) sync();
    }

    function sync() {
        var need = paint() && !frozen();
        if (need && timer === null) timer = setInterval(tick, STEP_MS);
        else if (!need && timer !== null) { clearInterval(timer); timer = null; }
        watchCovers();
    }

    function watchCovers() {
        if (typeof MutationObserver !== 'function') return;
        if (covered && !coverObserver) {
            coverObserver = new MutationObserver(sync);
            coverObserver.observe(root, { attributes: true, subtree: true, attributeFilter: ['class', 'data-parked-terminals'] });
        } else if (!covered && coverObserver) { coverObserver.disconnect(); coverObserver = null; }
    }

    document.addEventListener('animationstart', function (e) {
        var name = e.animationName;
        var el = e.target;
        if (!name || name.indexOf(JOIN) !== 0 || !el || el.nodeType !== 1) return;
        wearers.set(el, name.slice(JOIN.length));
        el.setAttribute('data-amb', '');
        sync();
    }, true);

    document.addEventListener('visibilitychange', sync);
    document.addEventListener('carnivore:calm', sync);
    document.addEventListener('carnivore:amb-visibility', sync);
    if (typeof matchMedia === 'function') {
        var mq = matchMedia('(prefers-reduced-motion: reduce)');
        if (mq && typeof mq.addEventListener === 'function') mq.addEventListener('change', sync);
    }
    if (typeof MutationObserver === 'function') {
        new MutationObserver(sync).observe(root, { attributes: true, attributeFilter: ['data-calm', 'data-oc-still', 'data-motion', 'data-anim-off'] });
    }

    window.AmbientTicker = { steps: function () { return step; } };
})();
