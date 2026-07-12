// providers.ts — model registry + vendor adapters for the design-brief calls.
//
// Every active provider gets the same system prompt, user prompt and images and
// returns a raw (unvalidated) brief object; index.ts runs validateSpec() on each.
// Legs run in parallel with per-leg timeouts; one failed leg never sinks the
// request. Model ids are verified against live provider APIs — do not "correct"
// them from memory (see ~/.claude/LLM_MODELS.md).

import { BRIEF_JSON_SCHEMA, DESIGN_SYSTEM, parseBrief } from './spec.ts';

const ANTHROPIC_VERSION = '2023-06-01';
// Generous: a structured-output 400 → prompt-parse retry runs two vision calls
// back to back on one leg.
const LEG_TIMEOUT_MS = 40_000;

// Models that rejected output_config this instance — skip the doomed first call.
const noSchema = new Set<string>();

export type ProviderKey = 'haiku' | 'sonnet' | 'luna' | 'terra';

export interface ProviderDef {
  vendor: 'anthropic' | 'openai';
  model: string;
  label: string;
}

export interface Leg {
  key: ProviderKey;
  vendor: ProviderDef['vendor'];
  model: string;
  label: string;
  brief: unknown | null; // raw parsed JSON — validateSpec() runs in index.ts
  ms: number;
  usage: { input_tokens: number; output_tokens: number } | null;
  error?: string;
  note?: string; // e.g. 'prompt-parse-fallback' when structured outputs were rejected
}

// Fixed registry order → stable grid positions across runs (fair comparison).
export const PROVIDERS: Record<ProviderKey, ProviderDef> = {
  haiku: { vendor: 'anthropic', model: 'claude-haiku-4-5', label: 'Claude Haiku 4.5' },
  sonnet: {
    vendor: 'anthropic',
    model: Deno.env.get('SONNET_MODEL') ?? 'claude-sonnet-5',
    label: 'Claude Sonnet 5',
  },
  luna: { vendor: 'openai', model: 'gpt-5.6-luna', label: 'GPT-5.6 Luna' },
  terra: { vendor: 'openai', model: 'gpt-5.6-terra', label: 'GPT-5.6 Terra' },
};

/** Active legs from DESIGN_PROVIDERS (comma list). One leg = production mode. */
export function activeProviders(): ProviderKey[] {
  const wanted = (Deno.env.get('DESIGN_PROVIDERS') ?? 'haiku')
    .toLowerCase()
    .split(',')
    .map((s) => s.trim());
  const keys = (Object.keys(PROVIDERS) as ProviderKey[]).filter((k) => wanted.includes(k));
  return keys.length ? keys : ['haiku'];
}

export interface PromptInputs {
  userText: string;
  imageUrls: string[]; // screenshot, banner, logo — pre-flighted, max 3
}

interface LegSeed {
  key: ProviderKey;
  def: ProviderDef;
}

function normaliseUsage(u: any, vendor: ProviderDef['vendor']) {
  if (!u) return null;
  if (vendor === 'anthropic') {
    return { input_tokens: u.input_tokens ?? 0, output_tokens: u.output_tokens ?? 0 };
  }
  return { input_tokens: u.prompt_tokens ?? 0, output_tokens: u.completion_tokens ?? 0 };
}

async function callAnthropic(seed: LegSeed, inputs: PromptInputs, key: string, signal: AbortSignal): Promise<Leg> {
  const { def } = seed;
  const started = performance.now();
  const content: any[] = inputs.imageUrls.map((url) => ({
    type: 'image',
    source: { type: 'url', url },
  }));
  content.push({ type: 'text', text: inputs.userText });

  const body: Record<string, unknown> = {
    model: def.model,
    max_tokens: 1500,
    system: DESIGN_SYSTEM,
    messages: [{ role: 'user', content }],
  };
  const useSchema = !noSchema.has(def.model);
  if (useSchema) body.output_config = { format: { type: 'json_schema', schema: BRIEF_JSON_SCHEMA } };
  // Sonnet 5 defaults to adaptive thinking — slower and pricier than we need for
  // a design brief. Haiku 4.5 has no adaptive default; leave it untouched.
  if (def.model.startsWith('claude-sonnet')) body.thinking = { type: 'disabled' };

  const post = (b: Record<string, unknown>) =>
    fetch('https://api.anthropic.com/v1/messages', {
      method: 'POST',
      headers: { 'x-api-key': key, 'anthropic-version': ANTHROPIC_VERSION, 'content-type': 'application/json' },
      body: JSON.stringify(b),
      signal,
    });

  let note: string | undefined;
  let res = await post(body);
  if (useSchema && res.status === 400) {
    // Structured-output wire shape rejected (model/API drift) → prompt-and-parse.
    const errText = await res.text().catch(() => '');
    console.warn('anthropic structured-output fallback', def.model, errText.slice(0, 300));
    noSchema.add(def.model);
    note = 'prompt-parse-fallback';
    const { output_config: _drop, ...rest } = body;
    res = await post(rest);
  }
  if (!res.ok) {
    const errText = await res.text().catch(() => '');
    console.error('anthropic error', def.model, res.status, errText.slice(0, 300));
    return {
      ...legBase(seed),
      brief: null,
      ms: performance.now() - started,
      usage: null,
      error: 'http-' + res.status,
      ...(note ? { note } : {}),
    };
  }
  const data = await res.json();
  const usage = normaliseUsage(data?.usage, 'anthropic');
  const text: string = (data?.content || [])
    .filter((b: any) => b.type === 'text')
    .map((b: any) => b.text)
    .join('');
  const brief = parseBrief(text);
  return {
    ...legBase(seed),
    brief,
    ms: performance.now() - started,
    usage,
    ...(brief ? {} : { error: 'unparseable' }),
    ...(note ? { note } : {}),
  };
}

async function callOpenAI(seed: LegSeed, inputs: PromptInputs, key: string, signal: AbortSignal): Promise<Leg> {
  const { def } = seed;
  const started = performance.now();
  const parts: any[] = [{ type: 'text', text: inputs.userText }];
  // detail:'low' keeps each image at a small flat token cost — plenty for palette/mood.
  for (const url of inputs.imageUrls) parts.push({ type: 'image_url', image_url: { url, detail: 'low' } });

  const res = await fetch('https://api.openai.com/v1/chat/completions', {
    method: 'POST',
    headers: { Authorization: 'Bearer ' + key, 'content-type': 'application/json' },
    body: JSON.stringify({
      model: def.model,
      // Reasoning models spend from this budget on thinking BEFORE writing; too
      // low and content comes back empty (v1 shipped 800 — a latent bug).
      max_completion_tokens: 2500,
      reasoning_effort: Deno.env.get('OPENAI_REASONING_EFFORT') ?? 'low',
      response_format: { type: 'json_object' },
      messages: [
        { role: 'system', content: DESIGN_SYSTEM },
        { role: 'user', content: parts },
      ],
    }),
    signal,
  });
  if (!res.ok) {
    const errText = await res.text().catch(() => '');
    console.error('openai error', def.model, res.status, errText.slice(0, 300));
    return { ...legBase(seed), brief: null, ms: performance.now() - started, usage: null, error: 'http-' + res.status };
  }
  const data = await res.json();
  const usage = normaliseUsage(data?.usage, 'openai');
  const text: string = data?.choices?.[0]?.message?.content ?? '';
  if (!text) {
    return { ...legBase(seed), brief: null, ms: performance.now() - started, usage, error: 'empty-output' };
  }
  const brief = parseBrief(text);
  return {
    ...legBase(seed),
    brief,
    ms: performance.now() - started,
    usage,
    ...(brief ? {} : { error: 'unparseable' }),
  };
}

function legBase(seed: LegSeed): Pick<Leg, 'key' | 'vendor' | 'model' | 'label'> {
  return { key: seed.key, vendor: seed.def.vendor, model: seed.def.model, label: seed.def.label };
}

/** Run every active leg in parallel; a failed leg returns brief:null, never throws. */
export async function runDesigners(keys: ProviderKey[], inputs: PromptInputs): Promise<Leg[]> {
  const anthropicKey = Deno.env.get('ANTHROPIC_API_KEY');
  const openaiKey = Deno.env.get('OPENAI_API_KEY');

  const legs = await Promise.allSettled(
    keys.map(async (k) => {
      const seed: LegSeed = { key: k, def: PROVIDERS[k] };
      const apiKey = seed.def.vendor === 'anthropic' ? anthropicKey : openaiKey;
      if (!apiKey) return { ...legBase(seed), brief: null, ms: 0, usage: null, error: 'no-key' } as Leg;
      const ctl = new AbortController();
      const timer = setTimeout(() => ctl.abort(), LEG_TIMEOUT_MS);
      try {
        return seed.def.vendor === 'anthropic'
          ? await callAnthropic(seed, inputs, apiKey, ctl.signal)
          : await callOpenAI(seed, inputs, apiKey, ctl.signal);
      } catch (e) {
        const timedOut = ctl.signal.aborted;
        console.error('design leg failed', k, timedOut ? 'timeout' : e);
        return { ...legBase(seed), brief: null, ms: LEG_TIMEOUT_MS, usage: null, error: timedOut ? 'timeout' : 'fetch-failed' } as Leg;
      } finally {
        clearTimeout(timer);
      }
    }),
  );

  return legs.map((r, i) =>
    r.status === 'fulfilled'
      ? r.value
      : ({ ...legBase({ key: keys[i], def: PROVIDERS[keys[i]] }), brief: null, ms: 0, usage: null, error: 'settled-rejection' } as Leg),
  );
}
