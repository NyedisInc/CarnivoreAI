
console.log('[CommandDescription Module] Loading...');

(function () {
    const NARROW_MAX_CHARS = 90;
    const WIDE_MAX_CHARS = 240;
    const NARROW_VIEWPORT_MAX_PX = 600;

    const ELLIPSIS = '...';

    function maxChars(viewportWidth) {
        const w = typeof viewportWidth === 'number'
            ? viewportWidth
            : (typeof window !== 'undefined' ? window.innerWidth : 0);
        if (!w) return WIDE_MAX_CHARS;
        return w <= NARROW_VIEWPORT_MAX_PX ? NARROW_MAX_CHARS : WIDE_MAX_CHARS;
    }

    function shorten(text, limit) {
        const full = String(text == null ? '' : text).trim();
        const cap = typeof limit === 'number' ? limit : maxChars();
        if (full.length <= cap) return full;

        const budget = Math.max(1, cap - ELLIPSIS.length);
        let cut = full.slice(0, budget);
        const lastSpace = cut.lastIndexOf(' ');
        if (lastSpace > 0) cut = cut.slice(0, lastSpace);
        cut = cut.replace(/[\s.,;:!?-]+$/, '');
        return `${cut}${ELLIPSIS}`;
    }

    function isShortened(text, limit) {
        const full = String(text == null ? '' : text).trim();
        return shorten(full, limit) !== full;
    }

    window.CommandDescription = { shorten, isShortened, maxChars };
    console.log('[CommandDescription Module] Exported as window.CommandDescription');
})();
