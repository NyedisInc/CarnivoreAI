
console.log('[SessionRowActionsConfirm Module] Loading...');

(function () {
    var ACTION_CLOSE = 'close';
    var ACTION_REMOVE = 'remove';


    /* see the note above. */
    function catalogText(key, params) {
        return globalThis.CloudeTr(key, params);
    }

    function confirm(action, displayName, context) {
        const kind = action === ACTION_REMOVE ? ACTION_REMOVE : ACTION_CLOSE;
        const prefix = 'session.confirm.' + kind;
        return window.App.showConfirmModal(
            catalogText(prefix + '.title'),
            catalogText(prefix + '.message', { name: displayName }),
            catalogText(prefix + '.details', { attachment: attachmentPreamble(context) }),
            catalogText(prefix + '.primary'),
            catalogText('session.confirm.cancel'),
            'danger'
        );
    }

    function attachmentPreamble(context) {
        if (!context) return '';
        const sentences = [];
        if (context.openInApp) {
            sentences.push(catalogText('session.confirm.open_in_app'));
        }
        const attached = Number(context.attachedClients) || 0;
        if (attached > 0) {
            sentences.push(catalogText('session.confirm.attached_clients', { count: attached }));
        }
        return sentences.map(function (s) { return s + ' '; }).join('');
    }


    window.SessionRowActionsConfirm = {
        confirm: confirm,
        attachmentPreamble: attachmentPreamble,
    };
})();

console.log('[SessionRowActionsConfirm Module] Exported as window.SessionRowActionsConfirm');
