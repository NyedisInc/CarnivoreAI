(function () {
    'use strict';

    var STEP_MS = 42;
    var VAR = '--amb-step';
    var JOIN = 'amb-join-';
    var root = document.documentElement;
    var Motion = window.Motion;
    if (!Motion) return;

    var COVERS = 'body.menu-page-open > .screen, body.menu-page-open > .header, body.menu-page-open #session-notes-panel, ' +
        'body.menu-page-open .config-editor-picker-overlay, .oc-tabpane-hidden, .oc-tf-measure, [data-parked-terminals]';
    var COVERED = ':is(' + COVERS + ') *';

    var TYPE_VARS = {
        'dialog-glow': [VAR, '--amb-sheen-deg', '--pf-angle'],
        'avatar-spiral': [VAR, '--amb-spiral-deg'],
        'status-lights': [VAR, '--amb-led-deg', '--amb-led-op'],
        'drawer-bands': [VAR, '--amb-band-pos', '--amb-band-op'],
        'effort-badges': [
            VAR, '--amb-uc-op', '--amb-rb-a', '--amb-rb-b',
            '--amb-uc-sp-a', '--amb-uc-sc-a', '--amb-uc-sp-b', '--amb-uc-sc-b', '--amb-sheen-p'
        ],
        'sparks-steam': [
            VAR, '--amb-spark-op-a', '--amb-spark-y-a', '--amb-spark-sc-a',
            '--amb-spark-op-b', '--amb-spark-y-b', '--amb-spark-sc-b',
            '--amb-steam-op-1', '--amb-steam-y-1', '--amb-steam-op-2', '--amb-steam-y-2',
            '--amb-steam-op-3', '--amb-steam-y-3'
        ],
        'busy-pulses': [VAR, '--amb-pulse-op'],
        'terminal-ring': [VAR, '--amb-focus-op']
    };

    var wearers = new Map();
    var comets = new Map();
    var step = 0;
    var timer = null;
    var coverObserver = null;
    var covered = false;
    var hasPerf = typeof performance === 'object' && performance !== null && typeof performance.now === 'function';
    var epoch = hasPerf ? performance.now() : 0;

    function nowElapsed() {
        return hasPerf ? (performance.now() - epoch) : (step * STEP_MS);
    }

    function easeInOut(t) {
        return 0.5 - 0.5 * Math.cos(Math.PI * 2 * t);
    }

    function easeOut(t) {
        var u = 1 - t;
        return 1 - u * u;
    }

    function rainbowA(t) {
        if (t <= 0.05 || t >= 0.66) return 0;
        if (t < 0.25) return (t - 0.05) / 0.20;
        if (t <= 0.58) return 1;
        return 1 - (t - 0.58) / 0.08;
    }

    function rainbowB(t) {
        if (t <= 0.35) return 0;
        if (t < 0.55) return (t - 0.35) / 0.20;
        if (t <= 0.80) return 1;
        return 1 - (t - 0.80) / 0.20;
    }

    function sparkState(t) {
        var op = t < 0.2 ? (t / 0.2) * 0.9 : ((1 - t) / 0.8) * 0.9;
        var e = easeOut(t);
        return { op: op.toFixed(3), y: (-9 * e).toFixed(2) + 'px', sc: (0.6 + 0.4 * e).toFixed(3) };
    }

    function steamState(t) {
        var op = t < 0.3 ? (t / 0.3) * 0.85 : ((1 - t) / 0.7) * 0.85;
        var e = easeOut(t);
        return { op: op.toFixed(3), y: (1.5 - 4.0 * e).toFixed(2) };
    }

    function computeFrame(elapsed) {
        var cache = {};
        return function get(type) {
            if (cache[type]) return cache[type];
            var v = {};
            if (type === 'dialog-glow') {
                v.deg = (((elapsed % 6000) / 6000) * 360).toFixed(1) + 'deg';
            } else if (type === 'avatar-spiral') {
                v.deg = (-((elapsed % 2000) / 2000) * 360).toFixed(1) + 'deg';
            } else if (type === 'status-lights') {
                v.deg = (((elapsed % 750) / 750) * 360).toFixed(1) + 'deg';
                v.op = (1 - 0.6 * easeInOut((elapsed % 2000) / 2000)).toFixed(3);
            } else if (type === 'drawer-bands') {
                v.pos = (100 - ((elapsed % 4500) / 4500) * 100).toFixed(1) + '%';
                v.op = (1 - 0.45 * easeInOut((elapsed % 2800) / 2800)).toFixed(3);
            } else if (type === 'effort-badges') {
                var ucOp = 0.68 + 0.32 * (1 - easeInOut((elapsed % 2400) / 2400));
                var rbT = (elapsed % 3600) / 3600;
                var spA = easeInOut((elapsed % 1800) / 1800);
                var spB = easeInOut(((elapsed + 900) % 1800) / 1800);
                v.ucOp = ucOp.toFixed(3);
                v.rbA = rainbowA(rbT).toFixed(3);
                v.rbB = rainbowB(rbT).toFixed(3);
                v.spA = (spA * ucOp).toFixed(3);
                v.scA = (0.4 + 0.6 * spA).toFixed(3);
                v.spB = (spB * ucOp).toFixed(3);
                v.scB = (0.4 + 0.6 * spB).toFixed(3);
                v.sheenP = ((elapsed % 2600) / 2600).toFixed(4);
            } else if (type === 'sparks-steam') {
                v.skA = sparkState((elapsed % 2400) / 2400);
                v.skB = sparkState(((elapsed + 1200) % 2400) / 2400);
                v.st1 = steamState((elapsed % 2400) / 2400);
                v.st2 = steamState(((elapsed + 800) % 2400) / 2400);
                v.st3 = steamState(((elapsed + 1600) % 2400) / 2400);
            } else if (type === 'busy-pulses') {
                v.op = (1 - 0.4 * easeInOut((elapsed % 2400) / 2400)).toFixed(3);
            } else if (type === 'terminal-ring') {
                v.op = (0.65 + 0.30 * easeInOut((elapsed % 2400) / 2400)).toFixed(3);
            }
            cache[type] = v;
            return v;
        };
    }

    function clearWearer(el, type) {
        var vars = TYPE_VARS[type];
        if (!vars) { el.style.removeProperty(VAR); return; }
        for (var i = 0; i < vars.length; i++) el.style.removeProperty(vars[i]);
    }

    function applyWearer(el, type, get) {
        var st = el.style;
        st.setProperty(VAR, String(step));
        var v = get(type);
        if (type === 'dialog-glow') {
            st.setProperty('--amb-sheen-deg', v.deg);
            st.setProperty('--pf-angle', v.deg);
        } else if (type === 'avatar-spiral') {
            st.setProperty('--amb-spiral-deg', v.deg);
        } else if (type === 'status-lights') {
            st.setProperty('--amb-led-deg', v.deg);
            st.setProperty('--amb-led-op', v.op);
        } else if (type === 'drawer-bands') {
            st.setProperty('--amb-band-pos', v.pos);
            st.setProperty('--amb-band-op', v.op);
        } else if (type === 'effort-badges') {
            st.setProperty('--amb-uc-op', v.ucOp);
            st.setProperty('--amb-rb-a', v.rbA);
            st.setProperty('--amb-rb-b', v.rbB);
            st.setProperty('--amb-uc-sp-a', v.spA);
            st.setProperty('--amb-uc-sc-a', v.scA);
            st.setProperty('--amb-uc-sp-b', v.spB);
            st.setProperty('--amb-uc-sc-b', v.scB);
            st.setProperty('--amb-sheen-p', v.sheenP);
        } else if (type === 'sparks-steam') {
            st.setProperty('--amb-spark-op-a', v.skA.op);
            st.setProperty('--amb-spark-y-a', v.skA.y);
            st.setProperty('--amb-spark-sc-a', v.skA.sc);
            st.setProperty('--amb-spark-op-b', v.skB.op);
            st.setProperty('--amb-spark-y-b', v.skB.y);
            st.setProperty('--amb-spark-sc-b', v.skB.sc);
            st.setProperty('--amb-steam-op-1', v.st1.op);
            st.setProperty('--amb-steam-y-1', v.st1.y);
            st.setProperty('--amb-steam-op-2', v.st2.op);
            st.setProperty('--amb-steam-y-2', v.st2.y);
            st.setProperty('--amb-steam-op-3', v.st3.op);
            st.setProperty('--amb-steam-y-3', v.st3.y);
        } else if (type === 'busy-pulses') {
            st.setProperty('--amb-pulse-op', v.op);
        } else if (type === 'terminal-ring') {
            st.setProperty('--amb-focus-op', v.op);
        }
    }

    function readCometLapMs() {
        var raw = root && root.style && root.style.getPropertyValue ? root.style.getPropertyValue('--oc-comet-lap') : '';
        var parsed = parseFloat(raw);
        return (parsed > 0 && isFinite(parsed)) ? parsed * 1000 : 3000;
    }

    function frozen() {
        return root.getAttribute('data-calm') !== null || document.hidden === true || root.hasAttribute('data-oc-still');
    }

    function paint() {
        var need = false;
        covered = false;
        var elapsed = nowElapsed();
        var get = computeFrame(elapsed);
        var isReduced = Motion.reduced();

        wearers.forEach(function (type, el) {
            if (!el.isConnected) { wearers.delete(el); return; }
            if (isReduced || Motion.typeOff(type)) { clearWearer(el, type); return; }
            if (el.hasAttribute('data-anim-offscreen')) return;
            if (typeof el.matches === 'function' && el.matches(COVERED)) { covered = true; return; }
            applyWearer(el, type, get);
            need = true;
        });

        if (comets.size > 0) {
            var lapMs = readCometLapMs();
            var frac = (elapsed % lapMs) / lapMs;
            comets.forEach(function (cm, ring) {
                if (!ring.isConnected || !cm.host.isConnected) { comets.delete(ring); return; }
                if (isReduced) {
                    cm.bars.top.style.transform = '';
                    cm.bars.right.style.transform = '';
                    cm.bars.bottom.style.transform = '';
                    cm.bars.left.style.transform = '';
                    return;
                }
                if (cm.host.hasAttribute('data-anim-offscreen') || ring.hasAttribute('data-anim-offscreen')) return;
                if (typeof cm.host.matches === 'function' && cm.host.matches(COVERED)) { covered = true; return; }
                var p = cm.p;
                if (!(p > 0)) return;
                var s = (frac * p + cm.w / 2) % p;
                var pT = s;
                var pR = (s - cm.w + p) % p;
                var pB = (s - cm.w - cm.h + p) % p;
                var pL = (s - 2 * cm.w - cm.h + p) % p;
                cm.bars.top.style.transform = 'translate3d(' + pT.toFixed(1) + 'px,0,0)';
                cm.bars.right.style.transform = 'translate3d(0,' + pR.toFixed(1) + 'px,0)';
                cm.bars.bottom.style.transform = 'translate3d(' + (-pB).toFixed(1) + 'px,0,0)';
                cm.bars.left.style.transform = 'translate3d(0,' + (-pL).toFixed(1) + 'px,0)';
                need = true;
            });
        }
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
            var targets = new Set();
            if (document.body) targets.add(document.body);
            wearers.forEach(function (_type, el) {
                if (el && el.isConnected && typeof el.closest === 'function') {
                    var anc = el.closest('.oc-tabpane-hidden, .oc-tf-measure, [data-parked-terminals]');
                    if (anc) targets.add(anc);
                }
            });
            comets.forEach(function (cm) {
                if (cm.host && cm.host.isConnected && typeof cm.host.closest === 'function') {
                    var anc = cm.host.closest('.oc-tabpane-hidden, .oc-tf-measure, [data-parked-terminals]');
                    if (anc) targets.add(anc);
                }
            });
            if (!targets.size) targets.add(root);
            targets.forEach(function (target) {
                coverObserver.observe(target, { attributes: true, attributeFilter: ['class', 'data-parked-terminals'] });
            });
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

    function registerComet(ring, info) {
        if (!ring || !info) return;
        comets.set(ring, info);
        ring.setAttribute('data-amb', '');
        sync();
    }

    function unregisterComet(ring) {
        if (!ring) return;
        comets.delete(ring);
        sync();
    }

    window.AmbientTicker = {
        steps: function () { return step; },
        stepMs: function () { return STEP_MS; },
        registerComet: registerComet,
        unregisterComet: unregisterComet
    };
})();
