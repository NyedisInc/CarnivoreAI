
console.log('[KebabIcon Module] Loading...');

(function () {
    'use strict';

    var DEFAULT_SIZE = 20;

    var DEFAULT_RADIUS = 2;

    function svg(size, radius) {
        var px = (typeof size === 'number' && size > 0) ? size : DEFAULT_SIZE;
        var r = (typeof radius === 'number' && radius > 0) ? radius : DEFAULT_RADIUS;
        return (
            '<svg width="' + px + '" height="' + px + '" viewBox="0 0 16 16" fill="none" aria-hidden="true">' +
            '<circle cx="8" cy="3" r="' + r + '" fill="currentColor"/>' +
            '<circle cx="8" cy="8" r="' + r + '" fill="currentColor"/>' +
            '<circle cx="8" cy="13" r="' + r + '" fill="currentColor"/>' +
            '</svg>'
        );
    }

    window.KebabIcon = {
        svg: svg, DEFAULT_SIZE: DEFAULT_SIZE, DEFAULT_RADIUS: DEFAULT_RADIUS,
    };
})();

console.log('[KebabIcon Module] Exported as window.KebabIcon');
