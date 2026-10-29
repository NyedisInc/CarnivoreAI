(function () {
    'use strict';

    /* APP_TMUX_PREFIX */
    var APP_TMUX_PREFIX = 'cloude_';

    /* LABEL_MAX_CHARS */
    var LABEL_MAX_CHARS = 200;

    var CONTROL_CHARS = /[\x00-\x1f\x7f]/;

    var UNKNOWN = 'unknown session';

    function cleanString(value) {
        if (typeof value !== 'string') return null;
        var trimmed = value.trim();
        return trimmed.length ? trimmed : null;
    }

    function stripAppPrefix(tmuxName) {
        var name = cleanString(tmuxName);
        if (name === null) return null;
        if (name.indexOf(APP_TMUX_PREFIX) === 0) {
            name = name.slice(APP_TMUX_PREFIX.length);
        } else if (name.indexOf('carnivore_') === 0) {
            name = name.slice('carnivore_'.length);
        }
        if (!name.length) return null;
        var derived = name.split('_').join(' ').trim();
        return derived.length ? derived : null;
    }

    /* label: ' */
    function resolve(row, options) {
        if (!row || typeof row !== 'object') return null;
        var label = cleanString(row.label);
        if (label !== null) return label;
        var strip = !(options && options.stripPrefix === false);
        return strip ? stripAppPrefix(row.name) : cleanString(row.name);
    }

    function resolveToast(toast) {
        if (!toast || typeof toast !== 'object') return null;
        return resolve({ label: toast.session_label, name: toast.session_name });
    }

    function seedFromElement(el) {
        if (!el) return '';
        var full = el.dataset ? el.dataset.fullTitle : null;
        var value = (typeof full === 'string' && full.length)
            ? full
            : (el.textContent || '');
        return String(value).trim();
    }

    /**
     * The server's label rule, mirrored so an obviously bad label is
     * refused without a round trip. THE SERVER REMAINS AUTHORITATIVE -
     * this is an early out, never the decision.
     *
     * WHAT IT DELIBERATELY DOES NOT REFUSE. The rename controls used to
     * enforce ``^[A-Za-z0-9_-]{1,64}$``, the old TMUX NAME rule, against
     * a field that is no longer a tmux name. That regex refused "Media
     * Compression" - the feature's own worked example - before it could
     * reach a server that would have accepted it happily. Spaces, ``:``,
     * ``.``, quotes, ``$`` and non-ASCII are all legal in a label,
     * because a label is never handed to tmux. Only the server's own two
     * refusals are mirrored: empty, and control characters.
     *
     * Inputs: raw (string|null) - the value from an edit control.
     * Output: object - ``{ok: true, value: string}`` with surrounding
     *   whitespace stripped, or ``{ok: false, reason: string}`` carrying
     *   a sentence fit to show the user.
     * Example: SessionLabel.validate(' Image Tool ')
     *   // {ok: true, value: 'Image Tool'}
     */
    function validate(raw) {
        var cleaned = cleanString(raw);
        if (cleaned === null) {
            return { ok: false, reason: 'a session label cannot be empty' };
        }
        if (cleaned.length > LABEL_MAX_CHARS) {
            return {
                ok: false,
                reason: 'a session label may be at most '
                    + LABEL_MAX_CHARS + ' characters',
            };
        }
        if (CONTROL_CHARS.test(cleaned)) {
            return {
                ok: false,
                reason: 'a session label cannot contain control characters'
                    + ' such as a newline or a tab',
            };
        }
        return { ok: true, value: cleaned };
    }

    window.SessionLabel = {
        APP_TMUX_PREFIX: APP_TMUX_PREFIX,
        LABEL_MAX_CHARS: LABEL_MAX_CHARS,
        UNKNOWN: UNKNOWN,
        stripAppPrefix: stripAppPrefix,
        resolve: resolve,
        resolveToast: resolveToast,
        seedFromElement: seedFromElement,
        validate: validate,
    };
})();
