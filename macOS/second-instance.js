'use strict';

const { findLinkInArgv } = require('./deep-link');

const LOGIN_LAUNCH_ARG = '--login-launch';

const TOGGLE_ARG = '--toggle';

const MAX_ARGV = 256;

function isLoginLaunch(argv) {
  return Array.isArray(argv) && argv.length <= MAX_ARGV && argv.some((arg) => arg === LOGIN_LAUNCH_ARG);
}

function handleSecondInstance(argv) {
  const link = findLinkInArgv(argv);
  return {
    focus: !isLoginLaunch(argv),
    toggle: Array.isArray(argv) && argv.length <= MAX_ARGV && argv.includes(TOGGLE_ARG),
    links: link === null ? [] : [link],
  };
}

module.exports = { LOGIN_LAUNCH_ARG, TOGGLE_ARG, MAX_ARGV, isLoginLaunch, handleSecondInstance };
