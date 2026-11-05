
Object.assign(API.prototype, {
    async forkSession(sessionName) {
        return await this.call(
            `/sessions/${encodeURIComponent(sessionName)}/fork`,
            { method: 'POST' }
        );
    },

    /* the current session */
    async adoptSession(sessionName, confirmDetach = false, controller = null) {
        const vote = window.TerminalSizeVote;
        const grid = vote && typeof vote.adoptGrid === 'function' ? vote.adoptGrid(controller, document) : {};
        return await this.call('/sessions/adopt', {
            method: 'POST',
            body: {
                session_name: sessionName,
                confirm_detach: confirmDetach,
                ...(grid.cols && grid.rows
                    ? { cols: grid.cols, rows: grid.rows }
                    : {}),
            },
        });
    },
});
