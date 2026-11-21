
export const ROWS_BOTTOM_VAR = '--oc-frame-rows-bottom';

export function measureRowsBottom(root) {
    const top = root.getBoundingClientRect().top;
    let bottom = top;
    for (const el of chrome(root)) bottom = Math.max(bottom, el.getBoundingClientRect().bottom);
    return Math.round(bottom - top);
}

function chrome(root) {
    return [...root.querySelectorAll('.oc-titlebar, .oc-page__away')].filter(
        (el) => el.closest('.oc-page') === root && (el.classList.contains('oc-page__away') || el.parentElement === root),
    );
}

export function watchFrameStickyTop(root) {
    const update = () => root.style.setProperty(ROWS_BOTTOM_VAR, `${measureRowsBottom(root)}px`);
    const parts = chrome(root);
    const rows = parts.find((el) => el.classList.contains('oc-page__away')) ?? null;
    const sized = typeof ResizeObserver === 'function' ? new ResizeObserver(update) : null;
    for (const el of parts) sized?.observe(el);
    const classes = new MutationObserver(update);
    classes.observe(root, { attributes: true, attributeFilter: ['class'] });
    rows?.addEventListener('transitionend', update);
    update();
    return () => {
        sized?.disconnect();
        classes.disconnect();
        rows?.removeEventListener('transitionend', update);
        root.style.removeProperty(ROWS_BOTTOM_VAR);
    };
}
