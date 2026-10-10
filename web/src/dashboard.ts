import './dashboard.css';

type Config = Record<string, string | number | number[]>;
type Preset = { label: string; config: Config; repeats?: number };
const presets: Record<string, Preset> = {
  quick: { label: '動作確認（約13万手）', config: { timesteps: 131072 } },
  normal: { label: '通常学習（約105万手）', config: { timesteps: 1048576 } },
  repeat: { label: '通常学習・3seed（約105万手／回）', config: { timesteps: 1048576 }, repeats: 3 },
  long: { label: '長時間学習（約419万手）', config: { timesteps: 4194304 } },
  'long-repeat': { label: '長時間学習・3seed（約419万手／回）', config: { timesteps: 4194304 }, repeats: 3 },
  'low-rate': { label: '学習率0.0001（約105万手）', config: { timesteps: 1048576, learning_rate: 0.0001 } },
  'wide-network': { label: '隠れ層128,128（約105万手）', config: { timesteps: 1048576, hidden: [128, 128] } },
  'long-horizon': { label: '割引率0.999（約105万手）', config: { timesteps: 1048576, gamma: 0.999 } },
  'score-reward': { label: '得点比例報酬（約105万手）', config: { timesteps: 1048576, reward: 'score' } },
};
type Job = { id: string; kind: string; name: string; status: string; config?: Config; note: string; created: number; order: number; error?: string; parent?: string; best?: string; latest?: string; best_score?: number; condition?: Condition; baselines?: { agents: Record<string, { mean_score: number }> }; progress: Record<string, number | string>; history: History[] };
type History = { timesteps: number; seconds: number; validation_mean_score: number | null; validation_complete?: boolean };
type Model = { id: string; job: string | null; name: string; timesteps: number; created: number; zip: string | null; sha256: string; parent: string | null; seed_history_known: boolean };
type Condition = { id: string; name: string; purpose: string; seeds: number[]; max_steps: number };
type State = { environment: Record<string, boolean>; jobs: Job[]; models: Model[]; conditions: Condition[]; importable: string[] };
type Episode = { seed: number; score: string; moves: number; merged_max: string; terminated: boolean; truncated: boolean; inference_ms_per_move: number };
type Report = { complete: boolean; condition: Condition; agents: Record<string, { name: string; complete: boolean; episodes: Episode[]; mean_score: number | null; median_score: number | null; score_std: number | null; mean_moves: number | null; max_merged: string; truncated_episodes: number; mean_inference_ms: number | null; seed_history_known: boolean; reach_rates: Record<string, number>; representatives?: Record<string, number> }> };
const $ = <T extends HTMLElement = HTMLElement>(id: string) => document.getElementById(id) as T;
const input = (id: string) => $<HTMLInputElement>(id);
const select = (id: string) => $<HTMLSelectElement>(id);
const escape = (s: unknown) => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]!);
const number = (s: unknown) => typeof s === 'number' ? s.toLocaleString('ja-JP', { maximumFractionDigits: 2 }) : s == null ? '—' : escape(s);
const statuses: Record<string, string> = { queued: '待機', running: '実行中', stopping: '停止処理中', stopped: '保存して停止', completed: '完了', failed: '失敗', canceled: '取消', interrupted: '中断', imported: '取込済' };
const statusLabel = (j: Job) => j.status === 'stopped' && j.kind !== 'train' ? '中止' : statuses[j.status] || escape(j.status);
const token = document.querySelector<HTMLMetaElement>('meta[name=dtn-token]')!.content;
let state: State = { environment: {}, jobs: [], models: [], conditions: [], importable: [] }, defaults: Config;
let detailId = '', evaluationId = '', lastInventory = '', editId = '', detailPending = false, pollPending = false, jobsSignature = '';
let selectedJobs = new Set<string>(), selectedModels = new Set<string>(['random', 'greedy']);
const openModelGroups = new Set<string>();
const pending = new Map<string, string>();
let requestBusy = false;
let rebuildId = '';
let parentSequence = 0;
function normalizeTrainingNames() {
  const jobs = new Map(state.jobs.map(job => [job.id, job]));
  const models = new Map(state.models.map(model => [model.id, model]));
  const names = new Map<string, string>();
  function resolve(job: Job, visited = new Set<string>()): string {
    if (names.has(job.id)) return names.get(job.id)!;
    if (visited.has(job.id)) return job.name;
    visited.add(job.id);
    const model = job.parent ? models.get(job.parent) : undefined;
    const parent = model?.job ? jobs.get(model.job) : undefined;
    // Remove only a name produced by the old automatic naming rule;
    // keep names that the user entered or edited.
    const name = parent && job.name === model!.name + ' / 追加学習' ? resolve(parent, visited) : job.name;
    names.set(job.id, name);
    return name;
  }
  state.jobs.forEach(job => resolve(job));
  state.jobs.forEach(job => { job.name = names.get(job.id)!; });
  state.models.forEach(model => {
    const job = model.job ? jobs.get(model.job) : undefined;
    if (job && model.id.startsWith(job.id + '-step-')) model.name = `${job.name} / ${model.timesteps}手`;
  });
}
function experimentLabel(job: Job) {
  const parent = job.parent ? state.models.find(model => model.id === job.parent) : undefined;
  return parent ? `${job.name}（${parent.timesteps.toLocaleString('ja-JP')}手から）` : job.name;
}
function showError(e: unknown) { $('error-text').textContent = e instanceof Error ? e.message : String(e); $('error').hidden = false; }
function confirmAction(message: string) {
  const dialog = $<HTMLDialogElement>('confirm-dialog'); $('confirm-message').textContent = message;
  return new Promise<boolean>(resolve => { dialog.addEventListener('close', () => resolve(dialog.returnValue === 'ok'), { once: true }); dialog.showModal(); });
}
async function api(path: string, data?: Record<string, unknown>) {
  const response = await fetch('/api/' + path, data ? { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-DTN-Token': token }, body: JSON.stringify(data) } : { cache: 'no-store' });
  const result = await response.json(); if (!response.ok) throw Error(result.error || `HTTP ${response.status}`); return result;
}
async function action(path: string, data: Record<string, unknown>, unique = false) {
  if (requestBusy) return;
  requestBusy = true;
  const signature = path + JSON.stringify(data);
  if (unique) { if (!pending.has(signature)) pending.set(signature, crypto.randomUUID()); data = { ...data, request_id: pending.get(signature) }; }
  try { const result = await api(path, data); pending.delete(signature); await poll(); return result; }
  catch (e) { showError(e); }
  finally { requestBusy = false; }
}
const fields: [string, string, number, number, string?][] = [
  ['learning_rate', '学習率', .0000001, .1, '0.00001'], ['n_envs', '並列環境数', 1, 32], ['threads', 'CPUスレッド数', 1, 32],
  ['n_steps', 'ロールアウト手数／環境', 2, 8192], ['batch_size', 'バッチ数', 2, 8192], ['n_epochs', '更新回数', 1, 100],
  ['gamma', '割引率', .01, 1, '.001'], ['ent_coef', 'エントロピー係数', 0, 1, '.001'], ['max_steps', '1ゲームの手数上限', 1, 10000],
  ['checkpoint_steps', '保存・定期検証の間隔', 1, 10000000], ['eval_seed_start', '定期検証の開始seed', 0, 4294967295], ['eval_episodes', '定期検証のゲーム数', 1, 1000]
];
$('advanced').innerHTML = fields.map(([key, label, min, max, step]) => `<label>${label}<input id="cfg-${key}" type="number" min="${min}" max="${max}" step="${step ? 'any' : 1}" required></label>`).join('') + '<label>隠れ層（カンマ区切り）<input id="cfg-hidden" pattern="[0-9]+(,[0-9]+){0,2}" required></label><label>報酬方式<select id="cfg-reward"><option value="log_score">log2(1 + 合体得点) / 16</option><option value="score">合体得点 / 256</option></select></label>';
function fill(config: Config) {
  for (const [key] of fields) input('cfg-' + key).value = String(config[key]);
  input('cfg-hidden').value = (config.hidden as number[]).join(','); select('cfg-reward').value = String(config.reward);
  input('timesteps').value = String(config.timesteps); input('seed').value = String(config.seed);
}
function configuration(): Config {
  const config: Config = { ...defaults, timesteps: Number(input('timesteps').value), seed: Number(input('seed').value), hidden: input('cfg-hidden').value.split(',').map(Number), reward: select('cfg-reward').value };
  for (const [key] of fields) config[key] = Number(input('cfg-' + key).value);
  return config;
}
function page(id: string) {
  document.querySelectorAll<HTMLElement>('.page').forEach(el => el.hidden = el.id !== id);
  document.querySelectorAll<HTMLElement>('[data-page]').forEach(el => el.setAttribute('aria-selected', String(el.dataset.page === id)));
}
document.querySelectorAll<HTMLElement>('[data-page]').forEach(el => el.onclick = () => page(el.dataset.page!));
$('dismiss').onclick = () => { $('error').hidden = true; };
select('preset').innerHTML = Object.entries(presets).map(([id, preset]) => `<option value="${id}">${preset.label}</option>`).join('');
function trainingRepeats() { return select('parent').value ? 1 : presets[select('preset').value].repeats || 1; }
function updateTrainingButton() {
  const count = trainingRepeats();
  $('training-form').querySelector<HTMLButtonElement>('button[type=submit]')!.textContent = count === 1 ? '学習を登録' : `学習を登録（${count}件）`;
  input('seed').max = String(2 ** 32 - count);
}
select('preset').onchange = () => {
  select('parent').value = ''; void parentChanged();
  const preset = presets[select('preset').value];
  const seed = crypto.getRandomValues(new Uint32Array(1))[0] % (2 ** 32 - (preset.repeats || 1) + 1);
  fill({ ...defaults, ...preset.config, seed });
  updateTrainingButton();
};
async function parentChanged() {
  const sequence = ++parentSequence;
  const model = state.models.find(m => m.id === select('parent').value);
  $('parent-hint').hidden = !model;
  document.querySelectorAll<HTMLInputElement | HTMLSelectElement>('#advanced input,#advanced select').forEach(el => el.disabled = !!model);
  select('preset').disabled = !!model;
  updateTrainingButton();
  if (model) {
    const submit = $('training-form').querySelector<HTMLButtonElement>('button[type=submit]')!; submit.disabled = true;
    try { const result = await api('view?model=' + encodeURIComponent(model.id)); if (sequence !== parentSequence) return; fill({ ...result.policy.metadata.config, timesteps: 131072, seed: crypto.getRandomValues(new Uint32Array(1))[0] }); input('name').value = state.jobs.find(job => job.id === model.job)?.name || model.name; }
    catch (e) { showError(e); }
    finally { if (sequence === parentSequence) submit.disabled = false; }
  } else {
    $('training-form').querySelector<HTMLButtonElement>('button[type=submit]')!.disabled = false;
  }
}
select('parent').onchange = () => { void parentChanged(); };
$('training-form').onsubmit = async e => {
  e.preventDefault(); const result = await action('train', { config: configuration(), name: input('name').value, parent: select('parent').value || null, auto_evaluate: input('auto-evaluate').checked, repeats: trainingRepeats() }, true);
  if (result) { $('training-result').textContent = '登録しました'; detailId = result.ids[0]; await updateDetail(); }
};
$('evaluation-form').onsubmit = async e => { e.preventDefault(); const result = await action('evaluate', { models: [...selectedModels], condition: select('condition').value }, true); if (result) { evaluationId = result.id; await updateDetail(); } };
$('condition-form').onsubmit = async e => { e.preventDefault(); const result = await action('condition', { name: input('condition-name').value, purpose: select('purpose').value, seed_start: Number(input('condition-seed').value), episodes: Number(input('episodes').value), max_steps: Number(input('eval-limit').value) }, true); if (result) { select('condition').value = result.id; conditionInfo(); } };
async function setup() { const result = await action('setup', {}); if (result) rebuildId = result.id; }
$('setup').onclick = () => { void setup(); }; $('prepare').onclick = () => { void setup(); };
$('shutdown').onclick = async () => { if (await confirmAction('実行中の学習は更新完了後に保存して停止します。管理サーバーを終了しますか？')) { await action('shutdown', {}); $('connection').textContent = 'サーバー終了'; } };
$('import-run').onclick = () => { if (select('import-existing').value) void action('import', { name: select('import-existing').value }); };
$('import-actor').onclick = () => input('actor-file').click();
input('actor-file').onchange = async () => { const file = input('actor-file').files?.[0]; if (!file) return; try { if (file.size > 2 * 1024 * 1024) throw Error('モデルは2MB以下にしてください。'); await action('import-policy', { policy: JSON.parse(await file.text()) }); } catch (e) { showError(e); } finally { input('actor-file').value = ''; } };
input('search').oninput = renderJobs;
input('model-search').oninput = renderModels;
$('collapse-models').onclick = () => { openModelGroups.clear(); renderModels(); };
select('axis').onchange = renderChart; select('smooth').onchange = renderChart;
function conditionInfo() { const c = state.conditions.find(c => c.id === select('condition').value); $('condition-info').textContent = c ? `${c.purpose} / ${c.seeds.length}ゲーム / seed ${c.seeds[0]}～${c.seeds.at(-1)} / 上限${c.max_steps}手 / prototype-v2 / 決定的推論` : ''; }
select('condition').onchange = conditionInfo;
function inventory() {
  const signature = JSON.stringify([state.models, state.conditions, state.importable, state.jobs.map(j => [j.id, j.name, j.best, j.latest])]); if (signature === lastInventory) return; lastInventory = signature;
  const values = ['parent', 'condition', 'import-existing'].map(id => select(id).value);
  select('parent').innerHTML = '<option value="">新規学習</option>' + state.models.filter(m => m.zip).map(m => `<option value="${m.id}">${escape(m.name)}</option>`).join('');
  select('condition').innerHTML = state.conditions.map(c => `<option value="${c.id}">${escape(c.name)} / ${c.seeds.length}ゲーム</option>`).join('');
  select('import-existing').innerHTML = '<option value="">既存実験を選択</option>' + state.importable.map(n => `<option>${escape(n)}</option>`).join('');
  ['parent', 'condition', 'import-existing'].forEach((id, i) => { if ([...select(id).options].some(o => o.value === values[i])) select(id).value = values[i]; });
  $('evaluation-targets').innerHTML = '<div class="targets">' + [{ id: 'random', name: 'ランダム' }, { id: 'greedy', name: '1手先評価' }, ...state.models].map(m => `<label class="check"><input type="checkbox" data-model="${m.id}" ${selectedModels.has(m.id) ? 'checked' : ''}>${escape(m.name)}</label>`).join('') + '</div>';
  $('evaluation-targets').querySelectorAll<HTMLInputElement>('[data-model]').forEach(el => el.onchange = () => { if (el.checked) selectedModels.add(el.dataset.model!); else selectedModels.delete(el.dataset.model!); });
  renderModels(); conditionInfo();
}
function progress(job: Job) {
  const p = job.progress, steps = Number(p.timesteps || 0), total = Number(p.target_timesteps || job.config?.timesteps || 0);
  let text = job.status === 'queued' ? '' : `${escape(p.phase || '')}`;
  if (job.kind === 'train' && steps) text += ` ${number(steps)}手 / ${number(total)}手 · ${number(p.seconds)}秒`;
  const learned = steps - Number(p.initial_timesteps || 0), rollout = Number(job.config?.n_envs || 1) * Number(job.config?.n_steps || 1);
  if (job.kind === 'train' && job.status === 'running' && p.phase === '学習' && learned >= rollout && total > steps) text += ` · 残り約${number(Number(p.seconds) / learned * (total - steps))}秒`;
  if (job.kind === 'evaluate' && p.total) text += ` ${p.completed}/${p.total}ゲーム`;
  return `<div class="job-progress">${text}</div>${job.status === 'running' && (total || p.total) ? `<progress max="${total || p.total}" value="${steps || p.completed || 0}"></progress>` : ''}`;
}
function jobButtons(job: Job) {
  let result = `<button data-detail="${job.id}">詳細</button>`;
  if (['queued', 'running', 'stopping'].includes(job.status)) result += `<button data-stop="${job.id}">${job.status === 'queued' ? '取消' : job.kind === 'train' ? '保存して停止' : '中止'}</button>`;
  if (job.status === 'stopping') result += `<button data-force="${job.id}">強制終了</button>`;
  if (job.status === 'queued') result += `<button data-up="${job.id}" aria-label="キューの順番を上げる">↑</button>`;
  if (job.best || job.latest) result += `<button data-continue="${job.best || job.latest}">追加学習</button>`;
  if (job.kind === 'evaluate' && !['queued', 'running', 'stopping'].includes(job.status)) result += `<button data-rerun="${job.id}">再実行</button>`;
  return result;
}
function wireJobs(container: HTMLElement) {
  container.querySelectorAll<HTMLElement>('[data-detail]').forEach(el => el.onclick = async () => { const j = state.jobs.find(j => j.id === el.dataset.detail)!; if (j.kind === 'evaluate') { evaluationId = j.id; page('evaluation'); } else { detailId = j.id; } await updateDetail(); });
  container.querySelectorAll<HTMLElement>('[data-stop]').forEach(el => el.onclick = () => { void action('stop', { id: el.dataset.stop }); });
  container.querySelectorAll<HTMLElement>('[data-force]').forEach(el => el.onclick = async () => { if (await confirmAction('保存前の更新は失われます。直近の保存まで戻して強制終了しますか？')) void action('stop', { id: el.dataset.force, force: true }); });
  container.querySelectorAll<HTMLElement>('[data-up]').forEach(el => el.onclick = () => { const keys = state.jobs.filter(j => j.status === 'queued').sort((a, b) => a.order - b.order).map(j => j.id), index = keys.indexOf(el.dataset.up!); if (index > 0) { [keys[index - 1], keys[index]] = [keys[index], keys[index - 1]]; void action('reorder', { ids: keys }); } });
  container.querySelectorAll<HTMLElement>('[data-continue]').forEach(el => el.onclick = () => { page('experiments'); select('parent').value = el.dataset.continue!; void parentChanged(); window.scrollTo({ top: 0, behavior: 'smooth' }); });
  container.querySelectorAll<HTMLElement>('[data-rerun]').forEach(el => el.onclick = () => { const job = state.jobs.find(j => j.id === el.dataset.rerun)!; const keys = (job as Job & { models: string[] }).models; void action('evaluate', { models: keys, condition: job.condition!.id }, true); });
}
function renderJobs() {
  const signature = JSON.stringify([state.jobs, input('search').value, [...selectedJobs]]); if (signature === jobsSignature) return; jobsSignature = signature;
  const jobs = state.jobs.filter(j => j.name.toLowerCase().includes(input('search').value.toLowerCase())).sort((a, b) => a.status === 'queued' && b.status === 'queued' ? a.order - b.order : b.created - a.created);
  $('jobs').innerHTML = jobs.length ? '<div class="table-wrap"><table><thead><tr><th>比較</th><th>実験</th><th>状態・進捗</th><th>操作</th></tr></thead><tbody>' + jobs.map(j => `<tr><td>${j.kind === 'train' ? `<input type="checkbox" data-chart="${j.id}" aria-label="${escape(j.name)}を比較" ${selectedJobs.has(j.id) ? 'checked' : ''}>` : ''}</td><td>${escape(j.name)}<div class="muted">${new Date(j.created * 1000).toLocaleString('ja-JP')}${j.best_score != null ? '<br>最高検証得点 ' + number(j.best_score) : ''}</div></td><td><span class="status">${statusLabel(j)}</span>${progress(j)}${j.error ? '<div class="muted">' + escape(j.error) + '</div>' : ''}</td><td><div class="row">${jobButtons(j)}</div></td></tr>`).join('') + '</tbody></table></div>' : '<p class="muted">実験を登録するとここに表示します。</p>';
  wireJobs($('jobs'));
  $('jobs').querySelectorAll<HTMLInputElement>('[data-chart]').forEach(el => el.onchange = () => { if (el.checked) selectedJobs.add(el.dataset.chart!); else selectedJobs.delete(el.dataset.chart!); renderChart(); });
  const evaluations = state.jobs.filter(j => j.kind === 'evaluate').sort((a, b) => b.created - a.created);
  $('evaluation-jobs').innerHTML = evaluations.length ? '<div class="table-wrap"><table><thead><tr><th>条件</th><th>状態</th><th>操作</th></tr></thead><tbody>' + evaluations.map(j => `<tr><td>${escape(j.name)}<div class="muted">${j.condition!.seeds.length}ゲーム × ${(j as Job & { models: string[] }).models.length}対象</div></td><td>${statusLabel(j)}${progress(j)}</td><td><div class="row">${jobButtons(j)}</div></td></tr>`).join('') + '</tbody></table></div>' : '<p class="muted">検証はまだありません。</p>';
  wireJobs($('evaluation-jobs'));
}
function renderChart() {
  const jobs = state.jobs.filter(j => j.kind === 'train' && selectedJobs.has(j.id)).map(j => ({ ...j, name: experimentLabel(j) })), axis = select('axis').value as 'timesteps' | 'seconds', smooth = Number(select('smooth').value);
  const series = jobs.map(j => ({ job: j, rows: j.history.filter(r => r.validation_mean_score != null && r.validation_complete !== false) }));
  const all = series.flatMap(s => s.rows), width = 1000, height = 260, left = 70, right = 25, top = 20, bottom = 40;
  const colors = ['#91bad9', '#d9ae82', '#92c7a9', '#c5a4d5', '#d78d9c', '#b4bf79'];
  if (!all.length) { $('chart').innerHTML = '<p class="muted">比較対象を選択してください。完了した定期検証の得点を表示します。</p>'; $('config-comparison').innerHTML = ''; return; }
  const baselines = jobs.flatMap(j => Object.entries(j.baselines?.agents || {}).map(([kind, r]) => ({ name: j.name + ' / ' + (kind === 'random' ? 'ランダム' : '1手先評価'), value: r.mean_score })));
  const maxX = Math.max(1, ...all.map(r => r[axis])), maxY = Math.max(1, ...all.map(r => r.validation_mean_score!), ...baselines.map(b => b.value));
  const x = (value: number) => left + value / maxX * (width - left - right), y = (value: number) => height - bottom - value / maxY * (height - top - bottom);
  let svg = `<svg viewBox="0 0 ${width} ${height}" role="img" aria-label="定期検証の平均得点推移">`;
  for (let i = 0; i <= 4; i++) { const yy = y(maxY * i / 4); svg += `<line x1="${left}" x2="${width - right}" y1="${yy}" y2="${yy}" stroke="#35404d"/><text x="${left - 10}" y="${yy + 4}" fill="#a6b7c7" text-anchor="end" font-size="12">${number(maxY * i / 4)}</text><text x="${x(maxX * i / 4)}" y="${height - 10}" fill="#a6b7c7" text-anchor="middle" font-size="12">${number(maxX * i / 4)}</text>`; }
  series.forEach((s, index) => { const color = colors[index % colors.length]; const points = s.rows.map((r, i) => { const window = s.rows.slice(Math.max(0, i - smooth + 1), i + 1); return `${x(r[axis])},${y(window.reduce((n, r) => n + r.validation_mean_score!, 0) / window.length)}`; }); svg += `<polyline points="${points.join(' ')}" fill="none" stroke="${color}" stroke-width="2"/>` + s.rows.map(r => `<circle cx="${x(r[axis])}" cy="${y(r.validation_mean_score!)}" r="3" fill="${color}"><title>${escape(s.job.name)}: ${number(r.validation_mean_score)}点 / ${number(r.timesteps)}手</title></circle>`).join(''); });
  baselines.forEach(b => { svg += `<line x1="${left}" x2="${width - right}" y1="${y(b.value)}" y2="${y(b.value)}" stroke="#8194a5" stroke-dasharray="6 5"><title>${escape(b.name)}: ${number(b.value)}点（同じ定期検証条件）</title></line>`; });
  $('chart').innerHTML = svg + '</svg><div class="legend">' + series.map((s, i) => `<span><i style="background:${colors[i % colors.length]}"></i>${escape(s.job.name)}</span>`).join('') + baselines.map(b => `<span>${escape(b.name)} ${number(b.value)}点（破線）</span>`).join('') + '</div>';
  const keys = ['seed', 'reward', 'learning_rate', 'hidden', 'n_envs', 'n_steps', 'eval_seed_start', 'eval_episodes', 'max_steps'];
  $('config-comparison').innerHTML = '<div class="table-wrap"><table><thead><tr><th>条件</th>' + jobs.map(j => `<th>${escape(j.name)}</th>`).join('') + '</tr></thead><tbody>' + keys.map(key => `<tr><th>${key}</th>${jobs.map(j => `<td>${escape(j.config?.[key])}</td>`).join('')}</tr>`).join('') + '</tbody></table></div>';
}
function renderModels() {
  const groups = new Map<string, { id: string; job?: Job; models: Model[] }>();
  for (const model of state.models) {
    const id = model.job || 'imported-policies';
    if (!groups.has(id)) groups.set(id, { id, job: state.jobs.find(job => job.id === model.job), models: [] });
    groups.get(id)!.models.push(model);
  }
  const query = input('model-search').value.trim().toLowerCase();
  const actions = (m: Model) => `<div class="row"><button data-watch="${m.id}">観戦</button>${m.zip ? `<button data-continue="${m.id}">追加学習</button>` : ''}<a href="/api/export/model/${m.id}">JSON</a><button data-eval-model="${m.id}">検証対象に追加</button></div>`;
  const title = (m: Model) => m.job && m.id.startsWith(m.job + '-step-') ? `${number(m.timesteps)}手` : escape(m.name);
  const labels = (m: Model, job?: Job) => [job?.latest === m.id ? '最新' : '', job?.best === m.id ? '最高検証得点' : ''].filter(Boolean).join(' / ');
  const visible = [...groups.values()].sort((a, b) => (b.job?.created ?? Math.max(...b.models.map(m => m.created))) - (a.job?.created ?? Math.max(...a.models.map(m => m.created))))
    .filter(group => (group.job ? experimentLabel(group.job) : '取り込みモデル').toLowerCase().includes(query));
  $('model-list').innerHTML = visible.length ? visible.map(group => {
    const { id, job } = group, name = job ? experimentLabel(job) : '取り込みモデル';
    const models = [...group.models].sort((a, b) => b.timesteps - a.timesteps || b.created - a.created);
    const latest = models.find(m => m.id === job?.latest) || models[0], best = models.find(m => m.id === job?.best);
    const featured = job ? [latest, ...(best && best.id !== latest.id ? [best] : [])] : [];
    return `<article class="model-group"><div class="model-group-heading"><h2>${escape(name)}</h2><span class="muted">${models.length}モデル${job ? ' · ' + new Date(job.created * 1000).toLocaleString('ja-JP') + ' · ' + statusLabel(job) : ''}</span></div>`
      + featured.map(m => `<div class="model-featured"><div><span class="model-tag">${labels(m, job) || '最新保存'}</span><strong>${title(m)}</strong></div>${actions(m)}</div>`).join('')
      + `<details data-model-group="${id}" ${openModelGroups.has(id) ? 'open' : ''}><summary>全${models.length}件のモデル</summary><div class="table-wrap model-checkpoints"><table><thead><tr><th>モデル／累計手数</th><th>採用</th><th>操作</th></tr></thead><tbody>`
      + models.map(m => `<tr><td>${title(m)}<div class="muted" title="${m.sha256}">SHA256 ${m.sha256.slice(0, 12)}${m.seed_history_known ? '' : '<br>seed履歴は不明'}</div></td><td>${labels(m, job)}</td><td>${actions(m)}</td></tr>`).join('')
      + '</tbody></table></div></details></article>';
  }).join('') : `<p class="muted">${state.models.length ? '該当する実験はありません。' : '保存モデルはまだありません。'}</p>`;
  $('model-list').querySelectorAll<HTMLDetailsElement>('[data-model-group]').forEach(el => el.ontoggle = () => {
    if (!el.isConnected) return;
    if (el.open) openModelGroups.add(el.dataset.modelGroup!); else openModelGroups.delete(el.dataset.modelGroup!);
  });
  wireJobs($('model-list'));
  $('model-list').querySelectorAll<HTMLElement>('[data-watch]').forEach(el => el.onclick = () => { const seed = Number(input('watch-seed').value); if (!Number.isInteger(seed) || seed < 0 || seed > 4294967295) { showError('観戦seedが不正です。'); return; } window.open(`/index.html?model=${el.dataset.watch}&seed=${seed}`, 'game'); });
  $('model-list').querySelectorAll<HTMLElement>('[data-eval-model]').forEach(el => el.onclick = () => { selectedModels.add(el.dataset.evalModel!); lastInventory = ''; inventory(); page('evaluation'); });
}
function reportHTML(key: string, report: Report) {
  const maxScore = Math.max(1, ...Object.values(report.agents).flatMap(r => r.episodes.map(e => Number(e.score))));
  let content = `<p>${report.complete ? '完了' : '途中結果'} / ${escape(report.condition.name)} / ${escape(report.condition.purpose)} / ${report.condition.seeds.length}ゲーム / seed ${report.condition.seeds[0]}～${report.condition.seeds.at(-1)} / 上限${report.condition.max_steps}手</p><div class="row">` + ['json', 'csv', 'html'].map(f => `<a href="/api/export/report/${key}?format=${f}">${f.toUpperCase()}を書き出す</a>`).join('') + '</div>';
  content += '<div class="table-wrap"><table><thead><tr><th>対象</th><th>完了数</th><th>平均得点</th><th>中央値</th><th>標準偏差</th><th>平均手数</th><th>最大値</th><th>状態</th></tr></thead><tbody>' + Object.values(report.agents).map(r => `<tr><td>${escape(r.name)}</td><td>${r.episodes.length}</td><td>${number(r.mean_score)}</td><td>${number(r.median_score)}</td><td>${number(r.score_std)}</td><td>${number(r.mean_moves)}</td><td>${escape(r.max_merged)}</td><td>${r.complete ? '完了' : '途中結果'}</td></tr>`).join('') + '</tbody></table></div>';
  content += `<p class="muted">${report.complete ? '全対象が同じ' + report.condition.seeds.length + ' seedで完了。' : '途中結果は対象ごとに完了数が異なることがあります。完了した同条件の結果で比較してください。'}</p>`;
  for (const [agent, r] of Object.entries(report.agents)) {
    content += `<h3>${escape(r.name)} <small class="muted">${r.complete ? '完了' : '途中結果'} ${r.episodes.length}ゲーム${r.seed_history_known ? '' : ' / seed履歴不明・未使用条件の認定不可'}</small></h3><div class="stats">` + [['平均得点', r.mean_score], ['中央値', r.median_score], ['標準偏差', r.score_std], ['平均手数', r.mean_moves], ['最大合成値', r.max_merged]].map(([title, value]) => `<div><small>${title}</small><strong>${number(value)}</strong></div>`).join('') + `</div><p class="muted">終了 ${r.episodes.length - r.truncated_episodes}ゲーム / 上限打ち切り ${r.truncated_episodes}ゲーム / 平均推論 ${number(r.mean_inference_ms)} ms／手</p>`;
    const scores = r.episodes.map(e => Number(e.score)), max = maxScore, bins = Array(10).fill(0) as number[]; scores.forEach(s => bins[Math.min(9, Math.floor(s / max * 10))]++);
    const highest = Math.max(1, ...bins); content += '<div class="histogram" aria-label="得点分布">' + bins.map((n, i) => `<div title="${Math.round(max * i / 10)}～${Math.round(max * (i + 1) / 10)}点: ${n}ゲーム"><small>${n}</small><span style="height:${n / highest * 100}px"></span><small>${Math.round(max * i / 10)}</small></div>`).join('') + '</div>';
    content += '<div class="table-wrap"><table><thead><tr>' + Object.keys(r.reach_rates).map(n => `<th>≥ ${n}</th>`).join('') + '</tr></thead><tbody><tr>' + Object.values(r.reach_rates).map(rate => `<td>${number(rate * 100)}%</td>`).join('') + '</tr></tbody></table></div><div class="row">';
    for (const [label, index] of Object.entries(r.representatives || {})) content += `<a href="/index.html?job=${key}&agent=${agent}&episode=${index}" target="game">${({ best: '最高得点', worst: '最低得点', median: '中央値付近' } as Record<string, string>)[label]}のリプレイ</a>`;
    content += '</div><details><summary>ゲーム別の結果・リプレイ</summary><div class="table-wrap"><table><thead><tr><th>seed</th><th>得点</th><th>手数</th><th>最大値</th><th>終了理由</th><th>記録</th></tr></thead><tbody>' + r.episodes.map((e, i) => `<tr><td>${e.seed}</td><td>${escape(e.score)}</td><td>${e.moves}</td><td>${escape(e.merged_max)}</td><td>${e.terminated ? 'ゲーム終了' : '上限'}</td><td><a href="/index.html?job=${key}&agent=${agent}&episode=${i}" target="game">再生</a> · <a href="/api/export/replay?job=${key}&agent=${agent}&episode=${i}">JSON</a></td></tr>`).join('') + '</tbody></table></div></details>';
  }
  return content;
}
async function updateDetail() {
  if (detailPending) return; detailPending = true;
  try {
    if (detailId) {
      const detail = await api('job/' + detailId); const job: Job = state.jobs.find(job => job.id === detailId) || detail.job;
      $('job-detail').hidden = false; $('detail-title').textContent = job.name;
      $('detail-summary').textContent = `${statuses[job.status]}${job.parent ? ' / 親 ' + job.parent : ''}${job.error ? ' / ' + job.error : ''}`;
      if (editId !== detailId) { input('edit-name').value = job.name; input('edit-note').value = job.note; editId = detailId; }
      $('detail-settings').textContent = JSON.stringify(detail.metadata || job.config || {}, null, 2);
      $('detail-metrics').textContent = detail.updates.length ? JSON.stringify(detail.updates.at(-1), null, 2) : '記録なし'; $('detail-log').textContent = detail.log || '記録なし';
    }
    if (evaluationId) {
      const detail = await api('job/' + evaluationId); $('evaluation-detail').hidden = false; $('evaluation-title').textContent = detail.job.name;
      const signature = JSON.stringify(detail.report); if ($('evaluation-results').dataset.signature !== signature) { $('evaluation-results').innerHTML = detail.report ? reportHTML(evaluationId, detail.report) : '<p class="muted">結果を待っています。</p>'; $('evaluation-results').dataset.signature = signature; }
    }
  } catch (e) { showError(e); }
  finally { detailPending = false; }
}
$('save-note').onclick = () => { if (detailId) void action('edit', { id: detailId, name: input('edit-name').value, note: input('edit-note').value }); };
$('copy-config').onclick = () => { const job = state.jobs.find(j => j.id === detailId); if (!job?.config || !job.config.hidden) return; select('parent').value = ''; void parentChanged(); fill({ ...job.config, seed: crypto.getRandomValues(new Uint32Array(1))[0] }); input('name').value = job.name + ' / 複製'; window.scrollTo({ top: 0, behavior: 'smooth' }); };
async function poll() {
  if (pollPending) return; pollPending = true;
  try {
    state = await api('state'); normalizeTrainingNames(); $('connection').textContent = 'ローカル接続'; $('environment').hidden = state.environment.ready;
    $('environment-info').textContent = `Python ${state.environment.python ? '導入済' : '不足'} / 学習依存 ${state.environment.rl ? '導入済' : '不足'} / 画面 ${state.environment.built ? '準備済' : '不足'}`;
    if (!selectedJobs.size) { const latest = [...state.jobs].reverse().find(j => j.kind === 'train'); if (latest) selectedJobs.add(latest.id); }
    inventory(); renderJobs(); renderChart(); await updateDetail();
    if (rebuildId && state.jobs.find(j => j.id === rebuildId)?.status === 'completed') location.reload();
  } catch { $('connection').textContent = '接続できません・再接続中'; }
  finally { pollPending = false; }
}
try { defaults = await api('defaults'); fill({ ...defaults, seed: crypto.getRandomValues(new Uint32Array(1))[0] }); await poll(); } catch (e) { showError(e); }
setInterval(() => { void poll(); }, 1000);
