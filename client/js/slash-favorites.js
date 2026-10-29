/* border-radius: 50% }` element rule
 * in styles.css exists for the round header icons and reaches every
 * button that does not opt out. Nine user-visible bugs have come from
 * that rule; height: 36px padding width: 36px */

console.log('[SlashFavorites Module] Loading...');

(function () {
    'use strict';

    function starIcon(on) {
        var d = 'M12 3.6l2.5 5.06 5.58.81-4.04 3.94.95 5.56L12 16.35l-4.99 2.62.95-5.56L3.92 9.47l5.58-.81z';
        return (
            '<svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true" focusable="false">' +
            '<path d="' + d + '" fill="' + (on ? 'currentColor' : 'none') + '"' +
            ' stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"/>' +
            '</svg>'
        );
    }

    function escapeHtml(str) {
        var div = document.createElement('div');
        div.textContent = str == null ? '' : String(str);
        return div.innerHTML;
    }

    /* <button> */
    function starButton(command, on) {
        var safe = escapeHtml(command);
        return (
            '<button type="button" class="command-star' + (on ? ' command-star--on' : '') + '"' +
            ' data-fav-toggle="' + safe + '"' +
            ' data-fav-state="' + (on ? '1' : '0') + '"' +
            ' aria-pressed="' + (on ? 'true' : 'false') + '"' +
            ' title="' + (on ? 'remove from favorites' : 'add to favorites') + '"' +
            ' aria-label="' + (on ? 'remove ' : 'add ') + safe + (on ? ' from favorites' : ' to favorites') + '">' +
            starIcon(on) +
            '</button>'
        );
    }

    function wire(root, onChange) {
        if (!root) return;
        root.querySelectorAll('[data-fav-toggle]').forEach(function (btn) {
            btn.addEventListener('click', function (e) {
                e.stopPropagation();
                e.preventDefault();
                if (btn.disabled) return;
                var command = btn.getAttribute('data-fav-toggle');
                var wanted = btn.getAttribute('data-fav-state') !== '1';
                btn.disabled = true;
                window.API.toggleFavoriteCommand(command, wanted).then(function (payload) {
                    if (onChange) onChange(payload);
                }).catch(function (err) {
                    console.error('[SlashFavorites] toggle failed', err);
                    btn.disabled = false;
                    window.alert(
                        'could not update favorites: ' +
                        (err && err.message ? err.message : 'unknown error')
                    );
                });
            });
        });
    }

    function favoriteSet(details) {
        var set = new Set();
        (details || []).forEach(function (d) {
            if (d && d.command) set.add(d.command);
        });
        return set;
    }

    function repaint(modal, opts) {
        if (!modal) return;

        var starred = favoriteSet(opts.details);
        modal.querySelectorAll('.command-item').forEach(function (item) {
            var old = item.querySelector('.command-star');
            if (!old) return;
            var command = item.dataset.command;
            var holder = document.createElement('div');
            holder.innerHTML = starButton(command, starred.has(command));
            old.replaceWith(holder.firstElementChild);
            wire(item, opts.onChange);
        });
    }

    window.SlashFavorites = {
        starButton: starButton,
        repaint: repaint,
        wire: wire,
        favoriteSet: favoriteSet,
    };
})();

console.log('[SlashFavorites Module] Exported as window.SlashFavorites');
