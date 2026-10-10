import './style.css';
import { EngineClient } from './client';
import { Renderer, compact, formatted, tileColor } from './renderer';
import type { Board, MoveEvent, Result, Session, Snapshot } from './types';

const el = <T extends HTMLElement = HTMLElement>(id: string) => document.getElementById(id) as T;
const renderer = new Renderer(el<HTMLCanvasElement>('board'));
const autoInput = el<HTMLInputElement>('auto-drop');
const STORAGE = 'drop-number.session.v1', BEST = 'drop-number.best.v1', PERIOD = 3500;
let client: EngineClient, state: Snapshot | undefined;
let busy = true, ready = false, paused = false, diagnostic = false, replaying = false;
let selected = 2, turnStart = performance.now(), pauseProgress = 0, replayRun = 0;
let imported: Session | undefined;
let best = '0';
let latency: number[] = [];
let runtimeLabel = '';
try { const stored = localStorage.getItem(BEST); if (stored && /^\d+$/.test(stored)) best = stored; } catch { /* Playing still works without storage. */ }
el('best').textContent = formatted(best);

function showError(text: string) { el('error-text').textContent = text; el('error-notice').hidden = false; }
function clearError() { el('error-notice').hidden = true; }
function errorMessage(error: unknown) { const text = error instanceof Error ? error.message : String(error); return text.trim().split('\n').at(-1)!.replace(/^\w*Error:\s*/, ''); }
function resetTimer(progress = 0) { turnStart = performance.now() - PERIOD * progress; pauseProgress = progress; }
function timerProgress() { return paused ? pauseProgress : Math.min(1, Math.max(0, (performance.now() - turnStart) / PERIOD)); }
function setPaused(value: boolean) {
  if (!ready || busy && !replaying || state?.over) return;
  if (value) { pauseProgress = timerProgress(); paused = true; if (replaying) replayRun++; }
  else { paused = false; resetTimer(pauseProgress); }
  controls();
}

function controls() {
  const locked = !ready || busy || replaying;
  for (const id of ['restart', 'export', 'import', 'apply-diagnostic', 'load-preset']) el<HTMLButtonElement>(id).disabled = locked;
  el<HTMLButtonElement>('restart-over').disabled = locked;
  el<HTMLButtonElement>('pause').disabled = !ready || (!!state?.over) || busy && !replaying;
  autoInput.disabled = locked || !!state?.over;
  el<HTMLButtonElement>('replay').disabled = locked || !imported?.actions.length;
  el('pause').textContent = replaying ? '再生を停止' : paused ? '再開' : '一時停止';
  el('over').hidden = !state?.over;
  el('paused-cover').hidden = !paused || !!state?.over || !ready;
  el('auto-label').textContent = autoInput.checked ? 'ON' : 'OFF';
  el('session-type').textContent = diagnostic ? '診断プレイ' : '通常プレイ';
}

function apply(result: Result) {
  state = result.state; diagnostic = result.diagnostic;
  renderer.board = state.board; renderer.current = state.current;
  renderer.showIncoming = !state.over;
  renderer.event = undefined;
  el('score').textContent = formatted(state.score);
  el('next-tile').textContent = compact(state.next);
  el('next-tile').title = state.next;
  const [bg, ink] = tileColor(state.next);
  el('next-tile').style.background = bg; el('next-tile').style.color = ink;
  el('max-tile').textContent = state.merged_max === '0' ? '—' : compact(state.merged_max);
  el('max-tile').title = state.merged_max;
  el('moves').textContent = String(state.moves);
  el('candidates').textContent = state.candidates.join(' · ');
  el('over-score').textContent = `SCORE ${formatted(state.score)}`;
  el('board-description').textContent = `得点${state.score}。現在${state.current}、次${state.next}。盤面は上から下へ: ${state.board.map(row => row.join('、')).join(' / ')}`;
  controls();
}

async function persist() {
  if (diagnostic || replaying) return;
  try { const session = await client.request<Session>({ command: 'export' }); localStorage.setItem(STORAGE, JSON.stringify(session)); }
  catch { showError('自動保存できませんでした。記録の書き出しで保存できます。'); }
}

function animate(event: MoveEvent, duration: number) {
  renderer.board = event.board; renderer.showIncoming = false; renderer.event = event;
  el('score').textContent = formatted(event.score);
  if (matchMedia('(prefers-reduced-motion: reduce)').matches || document.hidden) duration = 0;
  const start = performance.now();
  return new Promise<void>(resolve => {
    function frame(now: number) {
      renderer.eventProgress = duration ? Math.min(1, (now - start) / duration) : 1;
      renderer.draw();
      if (renderer.eventProgress < 1) requestAnimationFrame(frame);
      else resolve();
    }
    requestAnimationFrame(frame);
  });
}

async function drop(column: number, source = 'manual') {
  if (!ready || busy || paused || state?.over || replaying && source !== 'replay') return false;
  selected = column; renderer.selected = column;
  const elapsed = Math.round(performance.now() - turnStart);
  busy = true; clearError(); controls(); el('gain').textContent = '';
  try {
    const start = performance.now();
    const result = await client.request<Result>({ command: 'step', column, source, elapsed_ms: elapsed });
    latency.push(performance.now() - start);
    latency = latency.slice(-100);
    const ordered = [...latency].sort((a, b) => a - b);
    el('runtime-info').textContent = `${runtimeLabel} / 直近${ordered.length}手の応答中央値 ${ordered[Math.floor(ordered.length / 2)].toFixed(1)}ms`;
    if (!result.accepted) { showError(result.reason!); return false; }
    for (const event of result.events) await animate(event, event.kind === 'drop' ? source === 'auto' ? 0 : 170 : event.kind === 'gravity' ? 130 : event.kind === 'merge' ? 160 : 0);
    apply(result);
    if (result.score_delta !== '0') el('gain').textContent = `+${formatted(result.score_delta!)}`;
    if (!diagnostic && !replaying && BigInt(state!.score) > BigInt(best)) {
      best = state!.score; el('best').textContent = formatted(best);
      try { localStorage.setItem(BEST, best); } catch { /* Session download remains available. */ }
    }
    if (source !== 'replay') await persist();
    return true;
  } catch (error) { showError(errorMessage(error)); if (state) { renderer.board = state.board; renderer.current = state.current; renderer.showIncoming = !state.over; renderer.event = undefined; } return false; }
  finally { busy = false; resetTimer(); controls(); }
}

async function newGame() {
  if (busy || !ready) return;
  busy = true; paused = false; clearError(); controls();
  const input = el<HTMLInputElement>('seed').value;
  const seed = input === '' ? crypto.getRandomValues(new Uint32Array(1))[0] : Number(input);
  try {
    const result = await client.request<Result>({ command: 'new', seed, auto_drop: autoInput.checked });
    apply(result); imported = undefined; el('gain').textContent = '';
    await persist();
  } catch (error) { showError(errorMessage(error)); }
  finally { busy = false; resetTimer(); controls(); }
}

async function boot() {
  ready = false; busy = true; clearError(); controls();
  el('loading').hidden = false; el('retry').hidden = true;
  el('loading-title').textContent = 'ゲームを準備しています';
  client?.destroy();
  client = new EngineClient(text => { el('loading-status').textContent = text; });
  try {
    const info = await client.request<{ load_ms: number; python: string; pyodide: string }>({ command: 'boot', base: new URL(import.meta.env.BASE_URL, document.baseURI).href });
    runtimeLabel = `Python ${info.python} / Pyodide ${info.pyodide} / 起動 ${(info.load_ms / 1000).toFixed(2)}秒`;
    el('runtime-info').textContent = runtimeLabel;
    let saved: string | null = null, loaded = false;
    try { saved = localStorage.getItem(STORAGE); } catch { /* Storage may be unavailable. */ }
    if (saved) {
      try {
        const result = await client.request<Result>({ command: 'import', session: JSON.parse(saved) });
        apply(result); autoInput.checked = result.settings?.auto_drop ?? false;
        paused = true; loaded = true;
      } catch (error) { showError(`保存を復元できませんでした：${errorMessage(error)}。新規ゲームを用意しました。`); }
    }
    if (!loaded) {
      apply(await client.request<Result>({ command: 'new', seed: crypto.getRandomValues(new Uint32Array(1))[0] }));
    }
    ready = true; busy = false; el('loading').hidden = true; resetTimer(); controls();
  } catch (error) {
    el('loading-title').textContent = '読み込みできませんでした';
    el('loading-status').textContent = errorMessage(error); el('retry').hidden = false;
    busy = false; controls();
  }
}

function columns(stacks: number[][]): Board {
  const board = Array.from({ length: 6 }, () => Array<string>(5).fill('0'));
  stacks.forEach((stack, c) => stack.forEach((n, i) => { board[5 - i][c] = String(n); })); return board;
}

function preset(name: string) {
  const base = { board: columns([[], [], [], [], []]), current: '4', next: '2', score: '0', merged_max: '0', seed: 1, sequence: null };
  if (name === 'official-chain') return { ...base, board: columns([[32, 16, 64], [16, 8, 4], [8, 16], [2], [8]]), current: '4', score: '156', merged_max: '64' };
  if (name === 'triple') return { ...base, board: columns([[4, 16], [16], [], [], []]), current: '16', merged_max: '16' };
  if (name === 'ceiling-rescue' || name === 'ceiling-end') return { ...base, board: columns([[], [2, 4, 8, 32, 16], [], [], []]), current: name === 'ceiling-rescue' ? '16' : '8', merged_max: '32' };
  return base;
}

function fillPreset() {
  const name = el<HTMLSelectElement>('preset').value;
  const data = preset(name);
  el<HTMLTextAreaElement>('diagnostic-json').value = JSON.stringify(data, null, 2);
}

el('board').addEventListener('pointermove', event => { if (!busy && !paused && !replaying) { selected = renderer.column(event.clientX); renderer.selected = selected; controls(); } });
let pointerStart: [number, number] | undefined;
el('board').addEventListener('pointerdown', event => { if (event.button === 0) pointerStart = [event.clientX, event.clientY]; });
el('board').addEventListener('pointercancel', () => { pointerStart = undefined; });
el('board').addEventListener('pointerup', event => {
  if (pointerStart && Math.hypot(event.clientX - pointerStart[0], event.clientY - pointerStart[1]) < 10) void drop(renderer.column(event.clientX));
  pointerStart = undefined;
});
window.addEventListener('keydown', event => {
  if (event.repeat || !ready || busy || replaying || (event.target as HTMLElement)?.closest('input, textarea, select, summary')) return;
  if (/^[1-5]$/.test(event.key)) { event.preventDefault(); void drop(Number(event.key) - 1); }
  else if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') { event.preventDefault(); selected = (selected + (event.key === 'ArrowLeft' ? 4 : 1)) % 5; renderer.selected = selected; controls(); }
  else if ((event.key === 'Enter' || event.key === ' ') && !(event.target instanceof HTMLButtonElement)) { event.preventDefault(); void drop(selected); }
  else if (event.key.toLowerCase() === 'p') setPaused(!paused);
});
el('pause').addEventListener('click', () => setPaused(!paused));
el('resume').addEventListener('click', () => setPaused(false));
el('restart').addEventListener('click', () => { void newGame(); });
el('restart-over').addEventListener('click', () => { void newGame(); });
el('retry').addEventListener('click', () => { void boot(); });
el('dismiss-error').addEventListener('click', clearError);
autoInput.addEventListener('change', async () => {
  busy = true; clearError(); controls();
  try { await client.request({ command: 'settings', auto_drop: autoInput.checked }); resetTimer(); await persist(); }
  catch (error) { autoInput.checked = !autoInput.checked; showError(errorMessage(error)); }
  finally { busy = false; controls(); }
});
el('load-preset').addEventListener('click', fillPreset);
el('apply-diagnostic').addEventListener('click', async () => {
  if (busy) return;
  busy = true; clearError(); controls();
  try {
    const result = await client.request<Result>({ command: 'diagnostic', state: JSON.parse(el<HTMLTextAreaElement>('diagnostic-json').value) });
    autoInput.checked = false; paused = false; imported = undefined; apply(result); el('gain').textContent = '';
  } catch (error) { showError(errorMessage(error)); }
  finally { busy = false; resetTimer(); controls(); }
});
el('export').addEventListener('click', async () => {
  if (busy) return;
  busy = true; clearError(); controls();
  try {
    const session = await client.request<Session>({ command: 'export' });
    const url = URL.createObjectURL(new Blob([JSON.stringify(session, null, 2)], { type: 'application/json' }));
    const link = document.createElement('a'); link.href = url; link.download = `drop-number-${state!.seed}-${state!.moves}.json`; link.click();
    setTimeout(() => URL.revokeObjectURL(url), 5000);
  } catch (error) { showError(errorMessage(error)); }
  finally { busy = false; resetTimer(); controls(); }
});
el('import').addEventListener('click', () => el<HTMLInputElement>('file').click());
el<HTMLInputElement>('file').addEventListener('change', async event => {
  const input = event.target as HTMLInputElement, file = input.files?.[0]; if (!file) return;
  if (file.size > 4 * 1024 * 1024) { showError('記録は4MB以下のJSONで読み込んでください。'); input.value = ''; return; }
  busy = true; clearError(); controls();
  try {
    const session: Session = JSON.parse(await file.text());
    const result = await client.request<Result>({ command: 'import', session });
    imported = session; autoInput.checked = result.settings!.auto_drop; paused = true;
    apply(result); el('gain').textContent = ''; await persist();
  } catch (error) { showError(errorMessage(error)); }
  finally { input.value = ''; busy = false; resetTimer(); controls(); }
});
el('replay').addEventListener('click', async () => {
  if (!imported || busy) return;
  const original = imported, run = ++replayRun;
  busy = true; clearError(); controls();
  try {
    const initial = { ...original, actions: [], final: original.initial, settings: { ...original.settings, auto_drop: false } };
    const result = await client.request<Result>({ command: 'import', session: initial });
    autoInput.checked = false; paused = false; apply(result); replaying = true; busy = false; controls();
    for (const action of original.actions) {
      if (run !== replayRun) break;
      if (!await drop(action.column, 'replay')) throw new Error('記録の再生を継続できませんでした。');
      await new Promise(resolve => setTimeout(resolve, 250));
    }
  } catch (error) { showError(errorMessage(error)); }
  finally { replaying = false; busy = false; paused = true; resetTimer(); controls(); }
});
document.addEventListener('visibilitychange', () => { if (document.hidden && ready && !state?.over) { pauseProgress = timerProgress(); paused = true; if (replaying) replayRun++; controls(); } });

function frame() {
  if (ready && state) {
    const progress = autoInput.checked ? timerProgress() : 0;
    el('timer-progress').style.width = `${progress * 100}%`;
    if (!busy) { renderer.incomingProgress = state.over ? 0 : progress; renderer.draw(); }
    if (autoInput.checked && !paused && !busy && !replaying && !state.over && !document.hidden && progress >= 1) void drop(selected, 'auto');
  }
  requestAnimationFrame(frame);
}
fillPreset(); requestAnimationFrame(frame); void boot();
