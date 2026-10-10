/// <reference lib="webworker" />
import type { PyodideInterface } from 'pyodide';

let python: PyodideInterface;
let dispatch: { (raw: string): string; destroy(): void };
let queue = Promise.resolve();
const scope = self as unknown as DedicatedWorkerGlobalScope;

async function initialize(base: string) {
  const start = performance.now();
  scope.postMessage({ progress: 'Pythonランタイムを読み込んでいます…' });
  const runtime = new URL('runtime/', base).href;
  const { loadPyodide } = await import(/* @vite-ignore */ `${runtime}pyodide.mjs`);
  python = await loadPyodide({ indexURL: runtime });
  scope.postMessage({ progress: '共通ゲームエンジンを準備しています…' });
  const response = await fetch(new URL('engine/source.json', base));
  if (!response.ok) throw new Error(`エンジンの取得に失敗しました (${response.status})`);
  const files: Record<string, string> = await response.json();
  for (const [relative, source] of Object.entries(files)) {
    const absolute = `/game/${relative}`;
    python.FS.mkdirTree(absolute.slice(0, absolute.lastIndexOf('/')));
    python.FS.writeFile(absolute, source);
  }
  await python.runPythonAsync('import sys\nsys.path.insert(0, "/game")\nfrom drop_the_number.bridge import dispatch');
  dispatch = python.globals.get('dispatch');
  return { load_ms: Math.round(performance.now() - start), python: python.runPython('sys.version.split()[0]'), pyodide: python.version };
}

scope.onmessage = (message: MessageEvent<{ id: number; payload: Record<string, unknown> }>) => {
  const { id, payload } = message.data;
  queue = queue.then(async () => {
    try {
      const result = payload.command === 'boot'
        ? await initialize(payload.base as string)
        : JSON.parse(dispatch(JSON.stringify(payload)));
      scope.postMessage({ id, result });
    } catch (error) {
      scope.postMessage({ id, error: error instanceof Error ? error.message : String(error) });
    }
  });
};
