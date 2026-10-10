import { copyFile, mkdir, readdir, readFile, writeFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const root = fileURLToPath(new URL('../', import.meta.url));
const runtime = path.join(root, 'web/public/runtime');
const engine = path.join(root, 'web/public/engine');
await mkdir(runtime, { recursive: true });
await mkdir(engine, { recursive: true });
const pkg = path.join(root, 'web/node_modules/pyodide');
// Only the interpreter and standard library; no scientific or learning packages.
for (const file of ['pyodide.mjs', 'pyodide.asm.mjs', 'pyodide.asm.wasm', 'python_stdlib.zip', 'pyodide-lock.json']) {
  await copyFile(path.join(pkg, file), path.join(runtime, file));
}
const files = {};
async function collect(directory, prefix) {
  for (const item of await readdir(directory, { withFileTypes: true })) {
    const source = path.join(directory, item.name);
    const relative = `${prefix}/${item.name}`;
    if (item.isDirectory() && item.name !== '__pycache__') await collect(source, relative);
    else if (item.isFile() && item.name.endsWith('.py')) files[relative] = await readFile(source, 'utf8');
  }
}
await collect(path.join(root, 'src/drop_the_number'), 'drop_the_number');
await writeFile(path.join(engine, 'source.json'), JSON.stringify(files));
console.log(`Prepared local Pyodide runtime and ${Object.keys(files).length} Python sources.`);
