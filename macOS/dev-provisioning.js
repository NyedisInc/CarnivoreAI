
'use strict';

const fs = require('fs');
const path = require('path');

const REQUIRED_DIRS = ['src', 'client'];

const REQUIRED_FILES = ['setup_auth.py', 'requirements.txt', 'config.example.json', 'nuke.sh', '.env.example'];

function findPython({ baseDir, isPackaged }) {
  if (!isPackaged) {
    const localVenv = path.join(baseDir, 'venv', 'bin', 'python3');
    if (fs.existsSync(localVenv)) {
      console.log(`Using local venv Python: ${localVenv}`);
      return localVenv;
    }
  }
  const pythonLocations = [
    '/opt/homebrew/bin/python3',
    '/usr/local/bin/python3',
    '/usr/bin/python3',
    path.join(process.env.HOME || '', '.pyenv', 'shims', 'python3'),
  ];
  for (const location of pythonLocations) {
    if (fs.existsSync(location)) {
      console.log(`Found Python at: ${location}`);
      return location;
    }
  }
  console.log('Using python3 from PATH');
  return 'python3';
}

function copyRecursive(src, dest) {
  if (!fs.existsSync(dest)) fs.mkdirSync(dest, { recursive: true });
  for (const entry of fs.readdirSync(src, { withFileTypes: true })) {
    const srcPath = path.join(src, entry.name);
    const destPath = path.join(dest, entry.name);
    if (entry.isDirectory()) copyRecursive(srcPath, destPath);
    else fs.copyFileSync(srcPath, destPath);
  }
}

function ensureServerFiles({ baseDir, resourcesPath, isPackaged }) {
  if (!fs.existsSync(baseDir)) {
    console.log(`Creating baseDir: ${baseDir}`);
    fs.mkdirSync(baseDir, { recursive: true });
  }
  if (isPackaged) {
    for (const dir of REQUIRED_DIRS) {
      const srcPath = path.join(resourcesPath, dir);
      const destPath = path.join(baseDir, dir);
      if (fs.existsSync(srcPath) && !fs.existsSync(destPath)) {
        console.log(`Copying ${dir}/ to Application Support...`);
        copyRecursive(srcPath, destPath);
      }
    }
    for (const file of REQUIRED_FILES) {
      const srcPath = path.join(resourcesPath, file);
      const destPath = path.join(baseDir, file);
      if (fs.existsSync(srcPath) && !fs.existsSync(destPath)) {
        console.log(`Copying ${file} to Application Support...`);
        fs.copyFileSync(srcPath, destPath);
      }
    }
  }
  const srcDir = path.join(baseDir, 'src');
  if (!fs.existsSync(srcDir)) throw new Error(`Server source files not found at: ${srcDir}`);
}

function run(exec, command, failure) {
  return new Promise((resolve, reject) => {
    exec(command, (error) => {
      if (error) {
        console.error(failure, error);
        reject(error);
        return;
      }
      resolve();
    });
  });
}

async function ensureVenv({ baseDir, pythonPath, exec }) {
  const venvPath = path.join(baseDir, 'venv');
  const requirementsPath = path.join(baseDir, 'requirements.txt');
  const venvPython = path.join(venvPath, 'bin', 'python3');
  if (fs.existsSync(venvPath)) {
    if (!fs.existsSync(venvPython)) return null;
    console.log(`Using existing venv: ${venvPython}`);
    return venvPython;
  }
  console.log('Creating virtual environment...');
  await run(exec, `"${pythonPath}" -m venv "${venvPath}"`, 'Failed to create venv:');
  if (!fs.existsSync(requirementsPath)) return null;
  console.log('Installing requirements...');
  await run(exec, `"${venvPython}" -m pip install -r "${requirementsPath}"`, 'Failed to install requirements:');
  console.log('Venv setup complete');
  return venvPython;
}

module.exports = { REQUIRED_DIRS, REQUIRED_FILES, findPython, copyRecursive, ensureServerFiles, ensureVenv };
