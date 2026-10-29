'use strict';

const ENGINE_RESTART = 'restart';
const ENGINE_QUIT = 'quit';

/*  hidden  */
function createEngineDialogs({ dialog, loadTranslator, activate }) {
  const translator = async () => {
    try {
      return await loadTranslator();
    } catch (err) {
      console.error('[engine-dialogs] string catalog did not load:', err && err.message);
      return (key) => key;
    }
  };
  const show = (options) => {
    try {
      if (typeof activate === 'function') activate();
    } catch (err) {
      console.error('[engine-dialogs] could not raise the app before a dialog:', err && err.message);
    }
    return dialog.showMessageBox(options);
  };
  return {
    async askRestart({ runningVersion, bundleVersion }) {
      const t = await translator();
      const running = runningVersion || t('desktop.engine_restart.unknown_version');
      const answer = await show({
        type: 'warning',
        title: t('desktop.engine_restart.title'),
        message: t('desktop.engine_restart.title'),
        detail: t('desktop.engine_restart.detail', { running, bundle: bundleVersion }),
        buttons: [t('desktop.engine_restart.restart'), t('desktop.engine_restart.quit')],
        defaultId: 0,
        cancelId: 1,
      });
      return answer.response === 0 ? ENGINE_RESTART : ENGINE_QUIT;
    },

    /* could not */
    async showRestartFailed(reason) {
      const t = await translator();
      await show({
        type: 'error', title: t('desktop.engine_restart.failed_title'), message: t('desktop.engine_restart.failed_title'),
        detail: t('desktop.engine_restart.failed_detail', { reason }), buttons: [t('desktop.quit_notice.ok')],
      });
    },

    /* could not */
    async showStopFailed(reason) {
      const t = await translator();
      await show({
        type: 'error', title: t('desktop.engine_stop.failed_title'), message: t('desktop.engine_stop.failed_title'),
        detail: t('desktop.engine_stop.failed_detail', { reason }), buttons: [t('desktop.quit_notice.ok')],
      });
    },
  };
}

module.exports = { ENGINE_RESTART, ENGINE_QUIT, createEngineDialogs };
