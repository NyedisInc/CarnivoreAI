/* no longer holds */
(function () {
    'use strict';

    var TTL_MS = 60000;

    var MAX_ENTRIES = 500;

    function ToastDismissedRing(opts) {
        opts = opts || {};
        this._now = opts.now || function () { return Date.now(); };
        this._ttlMs = opts.ttlMs || TTL_MS;
        this._max = opts.maxEntries || MAX_ENTRIES;
        this._seen = new Map();
    }

    ToastDismissedRing.prototype.note = function (toastId) {
        if (!toastId) return;
        this._seen.delete(toastId);
        this._seen.set(toastId, this._now());
        this._evict();
    };

    ToastDismissedRing.prototype.has = function (toastId) {
        if (!toastId || !this._seen.has(toastId)) return false;
        var at = this._seen.get(toastId);
        if ((this._now() - at) > this._ttlMs) {
            this._seen.delete(toastId);
            return false;
        }
        return true;
    };

    ToastDismissedRing.prototype.filter = function (toasts) {
        if (!Array.isArray(toasts)) return [];
        var self = this;
        return toasts.filter(function (t) {
            return !(t && self.has(t.id));
        });
    };

    ToastDismissedRing.prototype.size = function () {
        return this._seen.size;
    };

    ToastDismissedRing.prototype._evict = function () {
        while (this._seen.size > this._max) {
            var oldest = this._seen.keys().next();
            if (oldest.done) return;
            this._seen.delete(oldest.value);
        }
    };

    ToastDismissedRing.TTL_MS = TTL_MS;
    ToastDismissedRing.MAX_ENTRIES = MAX_ENTRIES;

    window.ToastDismissedRing = ToastDismissedRing;
}());
