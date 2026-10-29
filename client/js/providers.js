(function () {
    const LAST_MODEL_KEY = 'cloude_provider_last_model';

    const LAST_MODEL_FIELD = 'launch_last_model';

    function readLastChoice() {
        const bridge = globalThis.PreferenceBridge;
        if (bridge && typeof bridge.read === 'function') {
            const shared = bridge.read(LAST_MODEL_FIELD, readLastChoiceLocally);
            return typeof shared === 'string' ? shared : '';
        }
        return readLastChoiceLocally();
    }

    function readLastChoiceLocally() {
        try {
            return localStorage.getItem(LAST_MODEL_KEY) || '';
        } catch (_) {
            return '';
        }
    }

    function rememberChoice(model) {
        const writeLocal = function () {
            try {
                localStorage.setItem(LAST_MODEL_KEY, model || '');
            } catch (_) {
            }
        };
        const bridge = globalThis.PreferenceBridge;
        if (bridge && typeof bridge.write === 'function') {
            bridge.write(LAST_MODEL_FIELD, model || '', writeLocal).catch(function (err) {
                console.warn('Providers: could not share the model choice', err);
            });
            return;
        }
        writeLocal();
    }

    function showProviderModal(opts) {
        const web = window.CloudeWeb;
        if (!web || typeof web.openLaunchPicker !== 'function') {
            console.error('Providers: the launch picker did not load');
            return Promise.resolve(null);
        }
        return web.openLaunchPicker({
            lastModel: readLastChoice(),
            projectDefault: (opts && opts.projectDefault) || null,
            accounts: !(opts && opts.accounts === false),
            remote: (opts && opts.remote) || null,
            goLabel: (opts && opts.goLabel) || null,
            prefill: (opts && opts.prefill) || null,
        }).then(function (pick) {
            if (!pick) return null;
            if (pick.model) rememberChoice(pick.model);
            return {
                model: pick.model,
                wrapperId: pick.profileId,
                accountId: pick.account ? pick.account.accountId : null,
                pinAccount: !!(pick.account && pick.account.pinned),
                farLauncher: !!pick.farLauncher,
                name: typeof pick.name === 'string' ? pick.name : null,
                pinned: pick.pinned === true,
            };
        });
    }

    window.Launchpad = window.Launchpad || {};
    window.Launchpad.showProviderModal = showProviderModal;
})();
