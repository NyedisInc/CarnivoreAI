
console.log('[API Api Config Files Module] Loading...');

if (typeof API !== 'function') {
    throw new Error(
        'api-config-files.js loaded before api.js - class API is not defined. '
        + 'Fix the script order in client/index.html.'
    );
}

Object.assign(API.prototype, {
    async getConfigFileTree(root, projectPath = null, opts = {}) {
        const params = new URLSearchParams({ root });
        if (projectPath) params.set('project_path', projectPath);
        if (opts && opts.path) params.set('path', opts.path);
        if (opts && opts.depth != null) params.set('depth', String(opts.depth));
        if (opts && opts.ignored) params.set('ignored', 'true');
        return await this.call(`/config-files/tree?${params.toString()}`);
    },

    async findConfigFiles(root, projectPath, opts) {
        const params = new URLSearchParams({ root, q: opts.q });
        if (projectPath) params.set('project_path', projectPath);
        if (opts.path) params.set('path', opts.path);
        if (opts.ignored) params.set('ignored', 'true');
        return await this.call(`/config-files/find?${params.toString()}`);
    },

    async readConfigFile(root, path, projectPath = null) {
        const params = new URLSearchParams({ root, path });
        if (projectPath) params.set('project_path', projectPath);
        return await this.call(`/config-files/read?${params.toString()}`);
    },

    async writeConfigFile(body) {
        return await this.call('/config-files/write', {
            method: 'POST',
            body,
        });
    },

    async createConfigFile(body) {
        return await this.call('/config-files/create', {
            method: 'POST',
            body,
        });
    },
});
