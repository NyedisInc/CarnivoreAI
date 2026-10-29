'use strict';


const MIN_MINOR = 12;
const MAX_PROVEN_MINOR = 14;
const MAJOR = 3;

function parsePythonVersion(text) {
  const match = /Python (\d+)\.(\d+)\.(\d+)/.exec(String(text || ''));
  if (!match) return null;
  const [major, minor, patch] = [match[1], match[2], match[3]].map((part) => parseInt(part, 10));
  return { major, minor, patch, text: `${major}.${minor}.${patch}` };
}

function classifyPython(text) {
  const parsed = parsePythonVersion(text);
  if (!parsed) return { verdict: 'unparsable', version: null };
  const { major, minor } = parsed;
  if (major > MAJOR || (major === MAJOR && minor > MAX_PROVEN_MINOR)) return { verdict: 'too-new', version: parsed.text };
  if (major < MAJOR || minor < MIN_MINOR) return { verdict: 'too-old', version: parsed.text };
  return { verdict: 'ok', version: parsed.text };
}

function tooNewMessage(version) {
  return `Python ${version} is newer than Carnivore's hash-locked install has been proven on `
    + `(Python ${MAJOR}.${MIN_MINOR} to ${MAJOR}.${MAX_PROVEN_MINOR}); install Python ${MAJOR}.${MIN_MINOR} to continue.`;
}

function venvNeedsRebuild(code, output) {
  return code !== 0 || classifyPython(output).verdict !== 'ok';
}

function buildPipInstallArgs(lockPath) {
  return ['install', '--disable-pip-version-check', '--require-hashes', '--only-binary', ':all:', '--no-deps', '-r', lockPath];
}

module.exports = {
  MIN_MINOR,
  MAX_PROVEN_MINOR,
  parsePythonVersion,
  classifyPython,
  tooNewMessage,
  venvNeedsRebuild,
  buildPipInstallArgs,
};
