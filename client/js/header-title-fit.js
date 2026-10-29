/* text-overflow: ellipsis */

console.log('[HeaderTitleFit Module] Loading...');

const ELLIPSIS = '…';

const MIN_TAIL_CHARS = 6;

const MIN_ELIDE_LENGTH = 8;

function buildCandidate(text, keep) {
    if (keep <= 0) return ELLIPSIS;
    if (keep >= text.length) return text;
    let tail = Math.max(Math.ceil(keep / 2), Math.min(MIN_TAIL_CHARS, keep));
    if (tail > keep) tail = keep;
    const head = keep - tail;
    return text.slice(0, head) + ELLIPSIS + text.slice(text.length - tail);
}

function elideToWidth(text, maxWidth, measure) {
    const full = String(text == null ? '' : text);
    if (!full) return '';
    if (!(maxWidth > 0)) return full;
    if (measure(full) <= maxWidth) return full;
    if (full.length < MIN_ELIDE_LENGTH) return full;

    let low = 0;
    let high = full.length - 1;
    let best = ELLIPSIS;
    while (low <= high) {
        const mid = Math.floor((low + high) / 2);
        const candidate = buildCandidate(full, mid);
        if (measure(candidate) <= maxWidth) {
            best = candidate;
            low = mid + 1;
        } else {
            high = mid - 1;
        }
    }
    return best;
}

function makeMeasurer(el) {
    const cs = window.getComputedStyle(el);
    const ruler = document.createElement('span');
    ruler.style.cssText =
        'position:absolute;visibility:hidden;white-space:pre;top:0;left:-9999px;' +
        'font:' + cs.font + ';letter-spacing:' + cs.letterSpacing;
    if (!cs.font) {
        ruler.style.fontFamily = cs.fontFamily;
        ruler.style.fontSize = cs.fontSize;
        ruler.style.fontWeight = cs.fontWeight;
        ruler.style.fontStyle = cs.fontStyle;
    }
    document.body.appendChild(ruler);
    const measure = (text) => {
        ruler.textContent = text;
        return ruler.getBoundingClientRect().width;
    };
    measure.dispose = () => { if (ruler.parentNode) ruler.remove(); };
    return measure;
}

function outerWidth(el, cs) {
    return el.getBoundingClientRect().width +
        (parseFloat(cs.marginLeft) || 0) +
        (parseFloat(cs.marginRight) || 0);
}

/* flex-shrink: 0 flex: 0 1 auto */
function slotWidth(el) {
    const parent = el.parentElement;
    if (!parent) return 0;
    const pcs = window.getComputedStyle(parent);
    let avail = parent.clientWidth -
        (parseFloat(pcs.paddingLeft) || 0) -
        (parseFloat(pcs.paddingRight) || 0);

    let visible = 0;
    for (const child of parent.children) {
        const cs = window.getComputedStyle(child);
        if (cs.display === 'none') continue;
        visible++;
        if (child === el) continue;
        avail -= outerWidth(child, cs);
    }

    const gap = parseFloat(pcs.columnGap) || parseFloat(pcs.gap) || 0;
    if (visible > 1) avail -= gap * (visible - 1);

    const ecs = window.getComputedStyle(el);
    avail -= (parseFloat(ecs.marginLeft) || 0) + (parseFloat(ecs.marginRight) || 0);
    return avail;
}

/* flex-shrink: 0 */
function availableWidth(titleEl) {
    const h1 = titleEl.parentElement;
    if (!h1 || !h1.parentElement) return 0;

    const hcs = window.getComputedStyle(h1);
    let avail = slotWidth(h1) -
        (parseFloat(hcs.paddingLeft) || 0) -
        (parseFloat(hcs.paddingRight) || 0);

    let visible = 0;
    for (const child of h1.children) {
        const cs = window.getComputedStyle(child);
        if (cs.display === 'none') continue;
        visible++;
        if (child === titleEl) continue;
        avail -= outerWidth(child, cs);
    }

    const gap = parseFloat(hcs.columnGap) || parseFloat(hcs.gap) || 0;
    if (visible > 1) avail -= gap * (visible - 1);
    return avail;
}

const HeaderTitleFit = {
    /** @type {Element|null} */
    _el: null,

    _cachedWidth: null,

    init() {
        if (this._el) return;
        const el = document.getElementById('header-title-text');
        if (!el) {
            console.warn('[HeaderTitleFit] no #header-title-text, skipping');
            return;
        }
        this._el = el;
        if (!el.dataset.fullTitle) el.dataset.fullTitle = el.textContent || '';

        const refit = () => { this.invalidateWidth(); this.refresh(); };
        window.addEventListener('resize', refit);
        window.addEventListener('orientationchange', refit);
        if (typeof window.ResizeObserver === 'function' && el.parentElement) {
            new window.ResizeObserver(refit).observe(el.parentElement);
        }
        if (window.document && window.document.fonts && window.document.fonts.ready
                && typeof window.document.fonts.ready.then === 'function') {
            window.document.fonts.ready.then(refit);
        }
        this.refresh();
        console.log('[HeaderTitleFit] initialized');
    },

    invalidateWidth() {
        this._cachedWidth = null;
    },

    /*  hidden  */
    _measuredWidth(el) {
        if (this._cachedWidth !== null) return this._cachedWidth;
        const w = availableWidth(el);
        if (w > 0) this._cachedWidth = w;
        return w;
    },

    setTitle(text) {
        const el = this._el || document.getElementById('header-title-text');
        if (!el) return;
        this._el = el;
        el.dataset.fullTitle = String(text == null ? '' : text);
        this.refresh();
    },

    refresh() {
        const el = this._el;
        if (!el) return;
        const full = el.dataset.fullTitle || '';
        const width = this._measuredWidth(el);
        if (!(width > 0)) {
            if (el.textContent !== full) el.textContent = full;
            return;
        }
        const measure = makeMeasurer(el);
        try {
            const fitted = elideToWidth(full, width, measure);
            if (el.textContent !== fitted) el.textContent = fitted;
        } finally {
            measure.dispose();
        }
    },

    _elideToWidth: elideToWidth,
    _buildCandidate: buildCandidate
};

window.HeaderTitleFit = HeaderTitleFit;

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => window.HeaderTitleFit.init());
} else {
    window.HeaderTitleFit.init();
}

console.log('[HeaderTitleFit Module] Exported as window.HeaderTitleFit');
