/* could not */

console.log('[VersionFooter Module] Loading...');

(function () {
    /** @type {string} The meta tag src/main.py stamps the version into. */
    const META_NAME = 'cloude-app-version';

    const RELEASE_NOTES_URL = 'https://github.com/NyedisInc/CarnivoreAI/releases';

    /* could not */
    const UNKNOWN_TEXT = 'version unknown';

    /** @type {RegExp} The major.minor.patch at the head of a build string. */
    const SHORT_VERSION_RE = /^v?(\d+\.\d+\.\d+)/;

    /** @type {RegExp} A preview build's marker inside its build string. */
    const PREVIEW_RE = /-preview/i;

    /** @type {string} The tiny marker word drawn after a preview build's short version. */
    const PREVIEW_TEXT = 'preview';

    let cachedVersion = null;

    function esc(value) {
        return String(value == null ? '' : value)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

    /* cannot determine */
    function readVersionText() {
        if (cachedVersion !== null) return cachedVersion;
        let content = '';
        try {
            const meta = document.querySelector(`meta[name="${META_NAME}"]`);
            content = meta ? (meta.getAttribute('content') || '').trim() : '';
        } catch (_) {
            content = '';
        }
        cachedVersion = content;
        return cachedVersion;
    }

    function resetCache() {
        cachedVersion = null;
    }

    /* <span class="version" user-select: none */
    function versionSpanHtml(extraClass) {
        const resolved = readVersionText();
        const text = resolved || UNKNOWN_TEXT;
        const cls = extraClass ? `version ${extraClass}` : 'version';
        return `<span class="${cls}">${esc(text)}</span>`;
    }

    function shortVersion(full) {
        const match = SHORT_VERSION_RE.exec(full);
        if (!match) return { text: full, preview: false };
        return { text: 'v' + match[1], preview: PREVIEW_RE.test(full) };
    }

    /* <span class="version" */
    function sidebarFooterHtml() {
        const resolved = readVersionText();
        const short = resolved ? shortVersion(resolved) : null;
        const span = !short || (short.text === resolved && !short.preview)
            ? versionSpanHtml()
            : `<span class="version">${esc(short.text)}`
                + (short.preview ? `<span class="version-footer__preview">${PREVIEW_TEXT}</span>` : '')
                + '</span>';
        if (!resolved) return `<div class="version-footer">${span}</div>`;
        return `<div class="version-footer">`
            + `<a class="version-footer__link" href="${esc(RELEASE_NOTES_URL)}"`
            + ' target="_blank" rel="noopener noreferrer">'
            + `${span}</a></div>`;
    }

    globalThis.VersionFooter = {
        META_NAME,
        RELEASE_NOTES_URL,
        UNKNOWN_TEXT,
        PREVIEW_TEXT,
        shortVersion,
        readVersionText,
        resetCache,
        versionSpanHtml,
        sidebarFooterHtml,
    };
    if (typeof module !== 'undefined' && module.exports) {
        module.exports = globalThis.VersionFooter;
    }

    console.log('[VersionFooter Module] Exported as window.VersionFooter');
})();
