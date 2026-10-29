
console.log('[SessionRowActionsConfirm Module] Loading...');

(function () {
    var ACTION_CLOSE = 'close';
    var ACTION_REMOVE = 'remove';

    const CONFIRM_COPY = {
        [ACTION_CLOSE]: {
            title: 'close session',
            primaryLabel: 'close',
            details:
                'this cannot be undone. the running process is terminated, ' +
                'and files uploaded to this session are removed from the ' +
                "project's .cloude_uploads folder. the transcript is kept " +
                'and stays under ~/.claude/projects.',
        },
        [ACTION_REMOVE]: {
            title: 'remove session',
            primaryLabel: 'remove',
            details:
                'this cannot be undone. this session already exited, so no ' +
                'running process is stopped, but files uploaded to it are ' +
                "removed from the project's .cloude_uploads folder. the " +
                'leftover tmux shell is cleared and carnivore forgets the ' +
                'entry. the transcript is kept and stays under ' +
                '~/.claude/projects.',
        },
    };

    function confirm(action, displayName, context) {
        const copy = CONFIRM_COPY[action] || CONFIRM_COPY[ACTION_CLOSE];
        const verb = action === ACTION_REMOVE ? 'remove' : 'close';
        return window.App.showConfirmModal(
            copy.title,
            `${verb} "${displayName}"?`,
            attachmentPreamble(context) + copy.details,
            copy.primaryLabel,
            'cancel',
            'danger'
        );
    }

    function attachmentPreamble(context) {
        if (!context) return '';
        let out = '';
        if (context.openInApp) {
            out += 'this session is open in carnivore right now, and that '
                + 'terminal will disconnect. ';
        }
        const attached = Number(context.attachedClients) || 0;
        if (attached > 0) {
            out += attached === 1
                ? '1 tmux client is attached to it right now and will be detached. '
                : `${attached} tmux clients are attached to it right now and `
                  + 'will be detached. ';
        }
        return out;
    }


    window.SessionRowActionsConfirm = {
        CONFIRM_COPY: CONFIRM_COPY,
        confirm: confirm,
        attachmentPreamble: attachmentPreamble,
    };
})();

console.log('[SessionRowActionsConfirm Module] Exported as window.SessionRowActionsConfirm');
