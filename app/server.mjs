import { createServer } from 'node:http';
import { readdirSync, readFileSync, existsSync, statSync, createReadStream } from 'node:fs';
import { mkdtemp, readFile, rm } from 'node:fs/promises';
import { dirname, resolve, join, sep } from 'node:path';
import { fileURLToPath } from 'node:url';
import { tmpdir } from 'node:os';
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';

const app = dirname(fileURLToPath(import.meta.url));
const root = resolve(app, '..');
const dataset = join(root, 'dataset');
const model = process.env.OKAPI_MODEL;
const pico = process.env.OKAPI_PICO;
const audio = [];
const documents = [];
const frequencies = new Map();
const stop = new Set('je tu il la le les un une des du de en et est ce que qui se a au pour avec comment dit on veux veut dire the a an is to how do you say in of what does mean and'.split(' '));
function normalize(text) {
  return text.toLowerCase().replaceAll('ɛ', 'e').replaceAll('ɔ', 'o').normalize('NFD').replace(/\p{M}/gu, '');
}
function terms(text) {
  return new Set((normalize(text).match(/[\p{L}\p{N}]+/gu) || []).filter(word => !stop.has(word)));
}
function rows(file) {
  return readFileSync(file, 'utf8').split(/\r?\n/).filter(line => line.trim()).map(line => JSON.parse(line));
}
function add(text, source, clip, headwords = [], lingala) {
  if (!text) return;
  const tokens = terms(text);
  for (const token of tokens) frequencies.set(token, (frequencies.get(token) || 0) + 1);
  documents.push({ text, source, clip, lingala, tokens, headwords: headwords.map(normalize) });
}
function ingest(file, label) {
  for (const row of rows(file)) {
    if (row.needs_review === true) continue;
    let clip;
    if (row.audio) {
      const path = resolve(dataset, row.audio);
      if (path.startsWith(dataset + sep) && path.endsWith('.wav') && existsSync(path)) {
        clip = audio.push(path) - 1;
      }
    }
    const text = [
      row.lingala, row.francais, row.question, row.reponse, row.section, row.texte,
      row.tableau, row.valeurs?.filter(Boolean).join(' · '),
    ].filter(Boolean).join(' — ');
    for (let offset = 0; offset < text.length; offset += 850) {
      add(text.slice(offset, offset + 950), row.title || label, clip,
        [row.lingala, row.francais].filter(Boolean), row.lingala || row.question);
    }
  }
}
for (const file of readdirSync(join(dataset, 'knowledge')).filter(name => name.endsWith('.jsonl'))) {
  ingest(join(dataset, 'knowledge', file), 'Wikipédia · Lingala');
}
for (const file of ['dialogues_qa.jsonl', 'phrases_ln.jsonl']) {
  ingest(join(dataset, 'sources', 'peace_corps', file), 'Peace Corps · Manuel de lingala');
}
ingest(join(dataset, 'sources', 'lrsc', 'metadata.jsonl'), 'LRSC · Enregistrement en lingala');
for (const entry of readdirSync(join(dataset, 'clips'), { withFileTypes: true }).filter(item => item.isDirectory())) {
  const file = join(dataset, 'clips', entry.name, 'metadata.jsonl');
  if (existsSync(file)) ingest(file, 'Extrait de cours');
}
for (const row of rows(join(dataset, 'sources', 'kaikki', 'kaikki.org-dictionary-Lingala.jsonl'))) {
  const glosses = row.senses?.flatMap(sense => sense.glosses || []) || [];
  if (row.word && glosses.length) add([row.word, ...glosses].join(' — '), 'Wiktionnaire · Kaikki', undefined, [row.word, ...glosses], row.word);
}

function search(query) {
  const tokens = terms(query);
  const normalized = [...tokens].join(' ');
  return documents.map(({ tokens: indexed, headwords, ...item }) => {
    let score = 0;
    for (const token of tokens) {
      if (indexed.has(token)) score += Math.log(1 + documents.length / frequencies.get(token));
    }
    if (score && headwords.includes(normalized)) score += 12;
    return { ...item, score: score / (1 + Math.log1p(indexed.size) * 0.12) };
  }).filter(item => item.score > 0).sort((a, b) => b.score - a.score);
}

function json(res, status, body) {
  res.writeHead(status, { 'Content-Type': 'application/json; charset=utf-8' });
  res.end(JSON.stringify(body));
}
async function requestBody(req) {
  let body = '';
  for await (const chunk of req.setEncoding('utf8')) {
    body += chunk;
    if (body.length > 24000) throw new Error('Message trop long.');
  }
  return JSON.parse(body);
}
async function chat(req, res) {
  const { message, language, history } = await requestBody(req);
  if (typeof message !== 'string' || !message.trim() || message.length > 2000) {
    return json(res, 400, { error: 'Écris un message de 1 à 2 000 caractères.' });
  }
  const english = language === 'en';
  const matches = search(message);
  const seen = new Set();
  const results = [];
  for (const item of matches) {
    const key = normalize(item.text);
    if (seen.has(key)) continue;
    seen.add(key);
    results.push(item);
    if (results.length === 4) break;
  }
  const recording = matches.find(item => item.clip !== undefined);
  if (recording && !results.includes(recording) && recording.score >= results[0].score * 0.55) results.push(recording);
  let reply = results.length
    ? (english ? 'Here are the closest entries in the Lingala collection.' : 'Voici les entrées les plus proches dans le corpus de lingala.')
    : (english ? 'I found no matching entry. Try a Lingala word or a short French expression.' : 'Je n’ai trouvé aucune entrée. Essaie un mot en lingala ou une expression courte en français.');
  let generated = false;
  let modelError;
  if (model) {
    const messages = Array.isArray(history) ? history.slice(-8).filter(item =>
      item && ['user', 'assistant'].includes(item.role) && typeof item.content === 'string')
      .map(item => ({ role: item.role, content: item.content.slice(0, 2000) })) : [];
    try {
      const response = await fetch('http://127.0.0.1:11434/api/chat', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, signal: AbortSignal.timeout(90000),
        body: JSON.stringify({ model, stream: false, messages: [
          { role: 'system', content: 'You are Okapi, a conversational assistant and Lingala tutor. Reply in ' +
            (english ? 'English' : 'French') + '. Use relevant corpus entries as reference material and say when a Lingala translation is uncertain.' },
          ...messages, { role: 'user', content: JSON.stringify({ question: message, corpus: results.map(({ text, source }) => ({ text, source })) }) },
        ] }),
      });
      if (!response.ok) throw new Error('Ollama HTTP ' + response.status);
      const answer = (await response.json()).message?.content?.trim();
      if (!answer) throw new Error('Réponse vide');
      reply = answer;
      generated = true;
    } catch {
      modelError = english ? 'The local model is unavailable.' : 'Le modèle local est indisponible.';
    }
  }
  json(res, 200, { reply, results, generated, modelError });
}

const server = createServer(async (req, res) => {
  const path = req.url;
  try {
    const host = req.headers.host;
    if (!host || !/^(localhost|127\.0\.0\.1)(:\d+)?$/.test(host) ||
        (req.headers.origin && req.headers.origin !== 'http://' + host)) {
      return json(res, 403, { error: 'Accès local uniquement.' });
    }
    if (req.method === 'GET' && path === '/') {
      res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' });
      return res.end(readFileSync(join(app, 'index.html')));
    }
    if (req.method === 'GET' && path === '/lingala.mjs') {
      res.writeHead(200, { 'Content-Type': 'text/javascript; charset=utf-8', 'Cache-Control': 'no-cache' });
      return res.end(readFileSync(join(app, 'lingala.mjs')));
    }
    if (req.method === 'GET' && path === '/api/status') {
      return json(res, 200, { entries: documents.length, recordings: audio.length, model: model || null, pico: Boolean(pico) });
    }
    if (req.method === 'POST' && path === '/api/chat') return await chat(req, res);
    if (req.method === 'GET' && /^\/audio\/\d+$/.test(path)) {
      const file = audio[Number(path.split('/').at(-1))];
      if (file) {
        res.writeHead(200, { 'Content-Type': 'audio/wav', 'Content-Length': statSync(file).size });
        const stream = createReadStream(file);
        stream.on('error', () => res.destroy());
        res.on('close', () => stream.destroy());
        return stream.pipe(res);
      }
    }
    if (req.method === 'POST' && path === '/api/speak' && pico) {
      const { text, language } = await requestBody(req);
      if (typeof text !== 'string' || !text.trim() || text.length > 3500) {
        return json(res, 400, { error: 'Texte audio invalide.' });
      }
      const folder = await mkdtemp(join(tmpdir(), 'okapi-'));
      try {
        const file = join(folder, 'voice.wav');
        await promisify(execFile)(pico, ['-l', language === 'en' ? 'en-US' : 'fr-FR', '-w', file, '--', text], { timeout: 15000 });
        const wav = await readFile(file);
        res.writeHead(200, { 'Content-Type': 'audio/wav', 'Content-Length': wav.length });
        return res.end(wav);
      } finally {
        await rm(folder, { recursive: true, force: true }).catch(() => {});
      }
    }
    json(res, 404, { error: 'Introuvable.' });
  } catch (error) {
    if (!res.headersSent) json(res, error instanceof SyntaxError ? 400 : 500, { error: 'Impossible de traiter cette demande.' });
    else res.destroy();
    console.error(error.message);
  }
});
server.listen(Number(process.env.OKAPI_PORT || 8787), '127.0.0.1', () => {
  console.log('OkapiAI · http://127.0.0.1:' + server.address().port + ' · ' + documents.length + ' entrées');
});
