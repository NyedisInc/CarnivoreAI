
console.log('[API Toasts Module] Loading...');

if (typeof API !== 'function') {
    throw new Error(
        'api-toasts.js loaded before api.js - class API is not defined. '
        + 'Fix the script order in client/index.html.'
    );
}

Object.assign(API.prototype, {
    async getAllToasts({ unackedOnly = true, limit = null } = {}) {
        const params = [`unacked=${unackedOnly ? 'true' : 'false'}`];
        if (limit) params.push(`limit=${encodeURIComponent(limit)}`);
        return await this.call(`/toasts?${params.join('&')}`);
    },
});
