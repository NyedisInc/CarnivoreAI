/* keyboard (`term.onData`), the Shift+Enter chord, the D-pad */

console.log('[TerminalInputOwnership Module] Loading...');

(function () {
    'use strict';

    function claim(what) {
        return {
            nav: window.NavigationGeneration
                ? window.NavigationGeneration.current()
                : null,
            // /input-focus.svelte.ts), published on
            owner: window.TerminalInputFocus
                ? window.TerminalInputFocus.current()
                : null,
            what: what || 'input'
        };
    }

    function permits(ticket) {
        if (!ticket) return true;
        if (!ownerPermits(ticket)) return false;
        if (ticket.nav == null) return true;
        if (!window.NavigationGeneration) return true;
        return window.NavigationGeneration.isCurrent(ticket.nav);
    }

    function ownerPermits(ticket) {
        var focus = window.TerminalInputFocus;
        if (!focus || typeof focus.current !== 'function') return true;
        if (ticket.owner == null) return true;
        var now = focus.current();
        if (now == null) return true;
        return now === ticket.owner;
    }

    function deliver(term, ticket) {
        if (permits(ticket)) return true;
        var what = (ticket && ticket.what) || 'input';
        console.debug('[input] dropped ' + what + ' for a session the user left',
            { nav: ticket && ticket.nav });
        if (term && typeof term._showStatusPill === 'function') {
            term._showStatusPill(what + ' dropped, you changed sessions', 'info');
        }
        return false;
    }

    function surfacePermits(owner) {
        if (!owner) return true;
        var focus = window.TerminalInputFocus;
        if (!focus || typeof focus.current !== 'function') return true;
        return focus.current() === owner;
    }

    window.TerminalInputOwnership = {
        claim: claim,
        surfacePermits: surfacePermits,
        permits: permits,
        ownerPermits: ownerPermits,
        deliver: deliver
    };
})();

console.log('[TerminalInputOwnership Module] Exported as window.TerminalInputOwnership');
