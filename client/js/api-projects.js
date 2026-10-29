
console.log('[API Projects Module] Loading...');

if (typeof API !== 'function') {
    throw new Error(
        'api-projects.js loaded before api.js - class API is not defined. '
        + 'Fix the script order in client/index.html.'
    );
}

Object.assign(API.prototype, {
    async getProjects(includeArchived = false) {
        return await this.call(
            includeArchived ? '/projects?include_archived=true' : '/projects'
        );
    },

    async archiveProject(name) {
        return await this.call(
            `/projects/${encodeURIComponent(name)}/archive`,
            { method: 'POST' }
        );
    },

    async unarchiveProject(name) {
        return await this.call(
            `/projects/${encodeURIComponent(name)}/unarchive`,
            { method: 'POST' }
        );
    },

    async getProjectsPresence() {
        return await this.call('/projects/presence');
    },

    /* could not be read */
    async getProjectsAuthority() {
        return await this.call('/projects/authority');
    },

    async createProject(params) {
        return await this.call('/projects', {
            method: 'POST',
            body: params
        });
    },

    async checkProjectRoot(path) {
        return await this.call('/projects/check-root', {
            method: 'POST',
            body: { path }
        });
    },

    async updateProject(currentName, { newName, description, defaultLaunchProfile, color } = {}) {
        const body = {};
        if (newName !== undefined) body.new_name = newName;
        if (description !== undefined) body.description = description;
        if (defaultLaunchProfile !== undefined) body.default_launch_profile = defaultLaunchProfile;
        if (color !== undefined) body.color = color;
        return await this.call(`/projects/${encodeURIComponent(currentName)}`, {
            method: 'PATCH',
            body
        });
    },

    async cloneProjectFromGithub({ repoUrl, parentDir, projectName, description } = {}) {
        const body = { repo_url: repoUrl };
        if (parentDir !== undefined && parentDir !== '') body.parent_dir = parentDir;
        if (projectName !== undefined && projectName !== '') body.project_name = projectName;
        if (description !== undefined) body.description = description;
        return await this.call('/projects/clone', {
            method: 'POST',
            body
        });
    },

    async browseDirectory(path = null) {
        const query = path ? `?path=${encodeURIComponent(path)}` : '';
        return await this.call(`/filesystem/browse${query}`);
    },

    async makeDirectory(path) {
        return await this.call('/filesystem/mkdir', {
            method: 'POST',
            body: { path }
        });
    },
});
