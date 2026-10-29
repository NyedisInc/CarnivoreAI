(function (global) {
    'use strict';

    var SETTLE_MS = 32;
    var EVENTS = ['scroll', 'transitionend', 'animationend', 'click'];

    var instances = [];
    var timer = null;
    var listening = false;
    var sizes = null;
    var watched = new Map();

    function rect(l, t, w, h) {
        return { x: l, y: t, left: l, top: t, width: w, height: h, right: l + w, bottom: t + h };
    }

    function schedule() {
        if (timer === null) timer = setTimeout(flush, SETTLE_MS);
    }

    function flush() {
        timer = null;
        instances.slice().forEach(function (o) {
            var records = o._collect();
            if (!records.length) return;
            try {
                o._callback.call(o, records, o);
            } catch (err) {
                console.error('VisibilityObserver: callback failed', err);
            }
        });
    }

    function listen() {
        if (listening) return;
        listening = true;
        EVENTS.forEach(function (n) { document.addEventListener(n, schedule, { capture: true, passive: true }); });
        window.addEventListener('resize', schedule);
        document.addEventListener('visibilitychange', schedule);
        if (typeof ResizeObserver === 'function') sizes = new ResizeObserver(schedule);
    }

    function unlisten() {
        if (!listening || instances.some(function (o) { return o._states.size; })) return;
        listening = false;
        EVENTS.forEach(function (n) { document.removeEventListener(n, schedule, true); });
        window.removeEventListener('resize', schedule);
        document.removeEventListener('visibilitychange', schedule);
        if (sizes) sizes.disconnect();
        sizes = null;
        watched.clear();
        if (timer !== null) clearTimeout(timer);
        timer = null;
    }

    function watch(el) {
        watched.set(el, (watched.get(el) || 0) + 1);
        if (sizes) sizes.observe(el);
    }

    function unwatch(el) {
        var n = (watched.get(el) || 0) - 1;
        if (n > 0) { watched.set(el, n); return; }
        watched.delete(el);
        if (sizes) sizes.unobserve(el);
    }

    function parseMargin(text, w, h) {
        var parts = String(text || '0px').trim().split(/\s+/);
        if (parts.length > 4) throw new SyntaxError('VisibilityObserver: bad rootMargin');
        var px = function (s, whole) {
            var m = /^(-?\d*\.?\d+)(px|%)$/.exec(s);
            if (!m) throw new SyntaxError('VisibilityObserver: bad rootMargin');
            return m[2] === '%' ? (parseFloat(m[1]) / 100) * whole : parseFloat(m[1]);
        };
        var t = px(parts[0], h);
        var r = parts.length > 1 ? px(parts[1], w) : t;
        var b = parts.length > 2 ? px(parts[2], h) : t;
        var l = parts.length > 3 ? px(parts[3], w) : r;
        return { t: t, r: r, b: b, l: l };
    }

    function intersect(a, b) {
        var l = Math.max(a.left, b.left), r = Math.min(a.right, b.right);
        var t = Math.max(a.top, b.top), bt = Math.min(a.bottom, b.bottom);
        return l > r || t > bt ? null : rect(l, t, r - l, bt - t);
    }

    function paddingBox(a) {
        var r = a.getBoundingClientRect();
        return rect(r.left + a.clientLeft, r.top + a.clientTop, a.clientWidth, a.clientHeight);
    }

    function measure(el, rootEl, margin) {
        var root = rootEl ? paddingBox(rootEl) : rect(0, 0, document.documentElement.clientWidth, document.documentElement.clientHeight);
        var m = parseMargin(margin, root.width, root.height);
        var bounds = rect(root.left - m.l, root.top - m.t, root.width + m.l + m.r, root.height + m.t + m.b);
        var none = { box: rect(0, 0, 0, 0), shown: null, bounds: bounds };
        if (!el.isConnected || el.getClientRects().length === 0) return none;
        var box = el.getBoundingClientRect();
        var shown = rect(box.left, box.top, box.width, box.height);
        var pos = getComputedStyle(el).position;
        if (pos !== 'absolute' && pos !== 'fixed') pos = 'static';
        for (var a = el.parentElement; a && pos !== 'fixed' && shown; a = a.parentElement) {
            if (a === rootEl || a === document.documentElement) break;
            var cs = getComputedStyle(a);
            if (pos === 'absolute' && cs.position === 'static') continue;
            if (cs.overflowX !== 'visible' || cs.overflowY !== 'visible') shown = intersect(shown, paddingBox(a));
            pos = cs.position === 'absolute' || cs.position === 'fixed' ? cs.position : 'static';
        }
        return { box: rect(box.left, box.top, box.width, box.height), shown: shown && intersect(shown, bounds), bounds: bounds };
    }

    function VisibilityObserver(callback, options) {
        if (typeof callback !== 'function') throw new TypeError('VisibilityObserver: callback must be a function');
        var o = options || {};
        this._callback = callback;
        this._root = o.root && o.root.nodeType === 1 ? o.root : null;
        this._margin = o.rootMargin === undefined ? '0px' : o.rootMargin;
        parseMargin(this._margin, 0, 0);
        var th = o.threshold === undefined ? [0] : [].concat(o.threshold);
        this._thresholds = th.map(Number).sort(function (x, y) { return x - y; });
        this._states = new Map();
        this.root = this._root;
        this.rootMargin = this._margin;
        this.thresholds = this._thresholds.slice();
    }

    VisibilityObserver.prototype.observe = function (el) {
        if (this._states.has(el)) return;
        this._states.set(el, { seen: false, hit: false, index: -1 });
        if (instances.indexOf(this) === -1) instances.push(this);
        listen();
        watch(el);
        if (this._root) watch(this._root);
        schedule();
    };

    VisibilityObserver.prototype.unobserve = function (el) {
        if (!this._states.delete(el)) return;
        unwatch(el);
        if (this._root) unwatch(this._root);
        if (!this._states.size) instances.splice(instances.indexOf(this), 1);
        unlisten();
    };

    VisibilityObserver.prototype.disconnect = function () {
        var self = this;
        Array.from(this._states.keys()).forEach(function (el) { self.unobserve(el); });
    };

    VisibilityObserver.prototype.takeRecords = function () {
        return this._collect();
    };

    VisibilityObserver.prototype._collect = function () {
        var out = [];
        var self = this;
        this._states.forEach(function (st, el) {
            var got = measure(el, self._root, self._margin);
            var area = got.box.width * got.box.height;
            var ratio = got.shown ? (area > 0 ? Math.min(1, (got.shown.width * got.shown.height) / area) : 1) : 0;
            var hit = got.shown !== null;
            var index = hit ? self._thresholds.filter(function (t) { return t <= ratio; }).length : 0;
            if (st.seen && st.hit === hit && st.index === index) return;
            st.seen = true; st.hit = hit; st.index = index;
            out.push({
                target: el, isIntersecting: hit, intersectionRatio: ratio, boundingClientRect: got.box,
                intersectionRect: got.shown || rect(0, 0, 0, 0), rootBounds: got.bounds, time: performance.now(),
            });
        });
        return out;
    };

    VisibilityObserver.during = function (fn) {
        var had = Object.prototype.hasOwnProperty.call(global, 'IntersectionObserver');
        var prev = global.IntersectionObserver;
        global.IntersectionObserver = VisibilityObserver;
        try {
            return fn();
        } finally {
            if (had) global.IntersectionObserver = prev;
            else delete global.IntersectionObserver;
        }
    };

    global.VisibilityObserver = VisibilityObserver;
})(typeof window !== 'undefined' ? window : globalThis);
