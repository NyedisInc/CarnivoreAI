
console.log('[SessionSidebarGroupColour Module] Loading...');

(function () {
    const COLOURS = ['cyan', 'violet', 'yellow', 'green', 'coral', 'orange', 'teal', 'rose', 'gold'];

    const HEX_COLOUR = /^#[0-9a-fA-F]{6}$/;

    const GRADIENTS = ['ember', 'tide', 'dusk', 'neon'];

    const ANIMATIONS = ['none', 'shimmer', 'pulse'];

    const GRADIENT_STOPS = {
        ember: ['orange', 'yellow'],
        tide: ['cyan', 'green'],
        dusk: ['violet', 'coral'],
        neon: ['cyan', 'violet'],
    };

    /** @type {HTMLElement|null} */
    let openPicker = null;
    /** @type {boolean} */
    let wired = false;

    function tr(key, params) {
        const i18n = globalThis.CloudeI18n;
        return (i18n && typeof i18n.t === 'function') ? i18n.t(key, params) : key;
    }

    function groupForKey(key) {
        const G = window.SessionSidebarGroupStore;
        if (!G || !G.isUsable()) return null;
        const uuid = G.groupUuidOf(key);
        return uuid ? G.groupByUuid(uuid) : null;
    }

    function styleAttrs(subject, prefix) {
        if (!subject) return '';
        const custom = HEX_COLOUR.test(subject.colour);
        if (!custom && !COLOURS.includes(subject.colour)) return '';
        const inline = custom && !GRADIENTS.includes(subject.gradient)
            ? ` style="${prefix === 'group' ? '--band-hue' : '--row-hue'}: ${subject.colour.toLowerCase()}"` : '';
        let out = ` data-${prefix}-colour="${custom ? 'custom' : subject.colour}"${inline}`;
        if (GRADIENTS.includes(subject.gradient)) out += ` data-${prefix}-gradient="${subject.gradient}"`;
        if (ANIMATIONS.includes(subject.animation) && subject.animation !== 'none') {
            out += ` data-${prefix}-anim="${subject.animation}"`;
        }
        return out;
    }

    function attrsFor(key) {
        return styleAttrs(groupForKey(key), 'group');
    }

    function layoutRowAttrs(layout) {
        return styleAttrs(layout, 'layout');
    }

    const FX_WINDOWS = 24;

    function fxHtml(attrs, prefix, text) {
        if (attrs.indexOf(` data-${prefix}-anim="shimmer"`) === -1) return '';
        const t = String(text).replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;');
        return `<span class="band-fx-host" data-anim-host aria-hidden="true"><span class="band-fx">${`<i data-t="${t}"></i>`.repeat(FX_WINDOWS)}</span></span>`;
    }

    function groupFxHtml(key, text) {
        return fxHtml(attrsFor(key), 'group', text);
    }

    function layoutFxHtml(layout, text) {
        return fxHtml(layoutRowAttrs(layout), 'layout', text);
    }

    function subjectFor(kind, id) {
        if (kind === 'group') {
            const G = window.SessionSidebarGroupStore;
            const group = G && G.isUsable() ? G.groupByUuid(id) : null;
            if (!group) return null;
            return {
                style: { colour: group.colour, gradient: group.gradient || null, animation: group.animation || 'none' },
                label: group.name,
                titleKey: 'sidebar.group.colour.title_named',
                failedKey: 'sidebar.group.colour.failed',
                write: async (style) => {
                    const body = await window.API.setSessionGroupStyle(id, style);
                    if (G) G.apply(body);
                    const actions = window.SessionSidebarGroupActions;
                    if (actions) actions.repaint();
                },
                onFailed: async () => {
                    const actions = window.SessionSidebarGroupActions;
                    if (actions) await actions.refresh();
                },
            };
        }
        if (kind === 'layout') {
            const web = window.CloudeWeb;
            const layouts = web && web.layouts;
            const layout = layouts && typeof layouts.get === 'function' ? layouts.get(id) : null;
            if (!layout) return null;
            return {
                style: { colour: layout.colour, gradient: layout.gradient || null, animation: layout.animation || 'none' },
                label: layout.name,
                titleKey: 'layout.row.colour.title_named',
                failedKey: 'layout.row.colour.failed',
                write: (style) => layouts.setStyle(id, style),
                onFailed: async () => {},
            };
        }
        return null;
    }

    function close() {
        if (openPicker && openPicker.parentNode) openPicker.parentNode.removeChild(openPicker);
        openPicker = null;
    }

    function optionHtml(o) {
        const esc = window.SessionSidebarRowControls.escHtml;
        return `<button type="button" role="radio" class="${o.cls}" `
            + `data-style-field="${o.field}" data-style-value="${o.value}" `
            + `aria-checked="${o.checked ? 'true' : 'false'}" `
            + (o.text ? '' : `title="${esc(o.label)}" `) + `aria-label="${esc(o.label)}"`
            + (o.style ? ` style="${o.style}"` : '')
            + `>${o.text ? esc(o.text) : ''}</button>`;
    }

    function pickerHtml(style) {
        const colourBtns = COLOURS.map((c) => optionHtml({
            field: 'colour', value: c, label: tr(`sidebar.group.colour.name.${c}`),
            checked: !style.gradient && style.colour === c,
            cls: 'group-colour-picker__swatch', style: `--swatch: var(--drawer-hue-${c})`,
        })).join('');
        const gradientBtns = GRADIENTS.map((g) => optionHtml({
            field: 'gradient', value: g, label: tr(`sidebar.group.colour.gradient.${g}`),
            checked: style.gradient === g,
            cls: 'group-colour-picker__swatch group-colour-picker__swatch--gradient',
            style: `--swatch: var(--drawer-hue-${GRADIENT_STOPS[g][0]}); `
                + `--swatch-2: var(--drawer-hue-${GRADIENT_STOPS[g][1]})`,
        })).join('');
        const animBtns = ANIMATIONS.map((a) => optionHtml({
            field: 'animation', value: a, label: tr(`sidebar.group.colour.anim.${a}`),
            text: tr(`sidebar.group.colour.anim.${a}`),
            checked: (style.animation || 'none') === a, cls: 'group-colour-picker__option',
        })).join('');
        const region = (labelKey, body, cls) => (
            '<div class="group-colour-picker__region">'
            + `<span class="group-colour-picker__label">${tr(labelKey)}</span>`
            + `<div class="${cls}" role="radiogroup" aria-label="${tr(labelKey)}">${body}</div></div>`
        );
        return `<div class="group-colour-picker__title">${tr('sidebar.group.colour.title')}</div>`
            + region('sidebar.group.colour.colours', colourBtns, 'group-colour-picker__swatches')
            + region('sidebar.group.colour.gradients', gradientBtns, 'group-colour-picker__swatches')
            + region('sidebar.group.colour.animation', animBtns, 'group-colour-picker__options');
    }

    function nextStyle(style, field, value) {
        const next = {
            colour: style.colour,
            gradient: style.gradient || null,
            animation: style.animation || 'none',
        };
        if (field === 'colour') { next.colour = value; next.gradient = null; }
        if (field === 'gradient') next.gradient = value;
        if (field === 'animation') next.animation = value;
        return next;
    }

    async function commitStyle(kind, id, style) {
        const subject = subjectFor(kind, id);
        if (!subject) return false;
        try {
            await subject.write(style);
            return true;
        } catch (err) {
            await subject.onFailed();
            const reason = err && err.message ? err.message : String(err);
            const notice = window.WriteFailureNotice;
            const text = tr(subject.failedKey, { reason });
            if (notice && typeof notice.report === 'function') notice.report(text);
            return false;
        }
    }

    function setStyle(groupUuid, style) {
        return commitStyle('group', groupUuid, style);
    }

    function redraw(el, style) {
        const focusedValue = document.activeElement && document.activeElement.dataset
            ? document.activeElement.dataset.styleValue : null;
        el.innerHTML = pickerHtml(style);
        const again = focusedValue && el.querySelector(`[data-style-value="${focusedValue}"]`);
        if (again) again.focus();
    }

    function openFor(anchor, kind, id) {
        const menu = window.SessionSidebarColorMenu;
        if (menu && typeof menu.open === 'function' && menu.open(anchor, kind, id)) return;
        openFull(anchor, kind, id);
    }

    function openFull(anchor, kind, id) {
        close();
        const subject = subjectFor(kind, id);
        if (!subject) return;
        const el = document.createElement('div');
        el.className = 'group-colour-picker popup-focus';
        el.setAttribute('role', 'dialog');
        el.setAttribute('aria-label', tr(subject.titleKey, { name: subject.label }));
        el.dataset.subjectKind = kind;
        el.dataset.subjectId = id;
        el.innerHTML = pickerHtml(subject.style);
        const box = anchor.getBoundingClientRect();
        el.style.top = `${Math.round(box.bottom + 2)}px`;
        document.body.appendChild(el);
        const left = Math.min(box.left, window.innerWidth - el.offsetWidth - 8);
        el.style.left = `${Math.max(8, Math.round(left))}px`;
        openPicker = el;
        el.addEventListener('click', async (e) => {
            const btn = e.target.closest && e.target.closest('[data-style-field]');
            if (!btn) return;
            e.preventDefault();
            e.stopPropagation();
            const current = subjectFor(kind, id);
            if (!current) { close(); return; }
            const style = nextStyle(current.style, btn.dataset.styleField, btn.dataset.styleValue);
            const ok = await commitStyle(kind, id, style);
            const fresh = subjectFor(kind, id);
            if (ok && fresh && openPicker === el) redraw(el, fresh.style);
        });
        const first = el.querySelector('[aria-checked="true"]') || el.querySelector('button');
        if (first) first.focus();
        wire();
    }

    function open(anchor, groupUuid) {
        openFor(anchor, 'group', groupUuid);
    }

    function wire() {
        if (wired) return;
        document.addEventListener('mousedown', (e) => {
            if (openPicker && !openPicker.contains(e.target)) close();
        });
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape' && openPicker) close();
        });
        wired = true;
    }

    window.SessionSidebarGroupColour = {
        COLOURS, GRADIENTS, ANIMATIONS, attrsFor, layoutRowAttrs, groupFxHtml, layoutFxHtml, open, openFor, openFull, close, nextStyle, setStyle,
    };
    console.log('[SessionSidebarGroupColour Module] Exported as window.SessionSidebarGroupColour');
})();
