
console.log('[WrapperMark Module] Loading...');

(function (root) {
    'use strict';

    function pickedSvg(icon, size) {
        if (typeof icon !== 'string' || !icon) return '';
        var glyphs = root.CloudeGlyphs;
        if (!glyphs || typeof glyphs.iconSvg !== 'function') return '';
        return glyphs.iconSvg(icon, size) || '';
    }

    function svg(wrapper, size) {
        var w = wrapper || {};
        var picked = pickedSvg(w.icon, size);
        if (picked) return picked;
        var family = root.AgentFamilyIcon;
        return family && typeof family.svg === 'function' ? family.svg(w.family, size) : '';
    }

    function source(wrapper) {
        return pickedSvg((wrapper || {}).icon, 12) ? 'icon' : 'family';
    }

    root.WrapperMark = { svg: svg, source: source };
})(typeof window !== 'undefined' ? window : globalThis);

console.log('[WrapperMark Module] Exported as window.WrapperMark');
