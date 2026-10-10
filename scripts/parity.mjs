import { spawnSync } from 'node:child_process';
import { readFile, readdir } from 'node:fs/promises';
import { fileURLToPath, pathToFileURL } from 'node:url';
import path from 'node:path';
import assert from 'node:assert/strict';

const root = fileURLToPath(new URL('../', import.meta.url));
const pythonPath = process.env.PARITY_PYTHON || path.join(root, '.venv', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python');
const reference = spawnSync(pythonPath, [path.join(root, 'scripts/parity_reference.py')], { cwd: root, encoding: 'utf8' });
if (reference.status !== 0) throw new Error(reference.stderr || 'CPython reference failed');
const calls = JSON.parse(reference.stdout);
const runtime = path.join(root, 'web/node_modules/pyodide');
const { loadPyodide } = await import(pathToFileURL(path.join(runtime, 'pyodide.mjs')).href);
const pyodide = await loadPyodide({ indexURL: runtime });
async function copySources(source, prefix) {
  pyodide.FS.mkdirTree(prefix);
  for (const item of await readdir(source, { withFileTypes: true })) {
    if (item.isDirectory() && item.name !== '__pycache__') await copySources(path.join(source, item.name), `${prefix}/${item.name}`);
    else if (item.isFile() && item.name.endsWith('.py')) pyodide.FS.writeFile(`${prefix}/${item.name}`, await readFile(path.join(source, item.name), 'utf8'));
  }
}
await copySources(path.join(root, 'src/drop_the_number'), '/game/drop_the_number');
pyodide.runPython('import sys\nsys.path.insert(0, "/game")\nfrom drop_the_number.bridge import dispatch');
const dispatch = pyodide.globals.get('dispatch');
for (const { request, result } of calls) {
  const actual = JSON.parse(dispatch(JSON.stringify(request)));
  assert.deepEqual(actual, result);
}
dispatch.destroy();
console.log(`CPython / Pyodide ${pyodide.version}: ${calls[0].result.length} fixtures and ${calls.length - 1} AI calls match, including actions, events, and random state.`);
