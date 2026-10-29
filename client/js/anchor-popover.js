
console.log('[AnchorPopover Module] Loading...');

(function () {
    'use strict';

    var MARGIN = 8;

    /* position: fixed */
    function place(el, anchor) {
        var rect = anchor.getBoundingClientRect();
        var vp = window.visualViewport || null;
        var vw = vp ? vp.width : window.innerWidth;
        var vh = vp ? vp.height : window.innerHeight;
        var offL = vp ? vp.offsetLeft : 0;
        var offT = vp ? vp.offsetTop : 0;

        var w = el.offsetWidth;
        var h = el.offsetHeight;

        var left = rect.right - w;
        var top = rect.top - h - MARGIN;
        if (top < offT + MARGIN) top = rect.bottom + MARGIN;

        left = Math.min(Math.max(left, offL + MARGIN), offL + vw - w - MARGIN);
        top = Math.min(Math.max(top, offT + MARGIN), offT + vh - h - MARGIN);

        el.style.left = left + 'px';
        el.style.top = top + 'px';
        return { left: left, top: top };
    }

    /* position: fixed */
    function placeAt(el, x, y) {
        var vp = window.visualViewport || null;
        var vw = vp ? vp.width : window.innerWidth;
        var vh = vp ? vp.height : window.innerHeight;
        var offL = vp ? vp.offsetLeft : 0;
        var offT = vp ? vp.offsetTop : 0;

        var w = el.offsetWidth;
        var h = el.offsetHeight;

        var left = x;
        var top = y;
        if (left + w > offL + vw - MARGIN) left = x - w;
        if (top + h > offT + vh - MARGIN) top = y - h;

        left = Math.min(Math.max(left, offL + MARGIN), offL + vw - w - MARGIN);
        top = Math.min(Math.max(top, offT + MARGIN), offT + vh - h - MARGIN);

        el.style.left = left + 'px';
        el.style.top = top + 'px';
        return { left: left, top: top };
    }

    /* position: fixed */
    function placeBelowLeft(el, anchor) {
        var rect = anchor.getBoundingClientRect();
        var vp = window.visualViewport || null;
        var vw = vp ? vp.width : window.innerWidth;
        var vh = vp ? vp.height : window.innerHeight;
        var offL = vp ? vp.offsetLeft : 0;
        var offT = vp ? vp.offsetTop : 0;

        var w = el.offsetWidth;
        var h = el.offsetHeight;

        var left = rect.left;
        var top = rect.bottom;

        if (left + w > offL + vw - MARGIN) left = rect.right - w;
        if (top + h > offT + vh - MARGIN) top = rect.top - h;

        left = Math.min(Math.max(left, offL + MARGIN), offL + vw - w - MARGIN);
        top = Math.min(Math.max(top, offT + MARGIN), offT + vh - h - MARGIN);

        el.style.left = left + 'px';
        el.style.top = top + 'px';
        return { left: left, top: top };
    }

    window.AnchorPopover = {
        place: place,
        placeAt: placeAt,
        placeBelowLeft: placeBelowLeft,
        MARGIN: MARGIN,
    };
})();

console.log('[AnchorPopover Module] Exported as window.AnchorPopover');
