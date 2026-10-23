# Local model setup — Mac / Windows / Linux

ShortsForge talks to any **OpenAI-compatible** endpoint. You need two roles,
which can be the same model: **writer** (drafts scripts) and **judge**
(quick publish/rewrite/discard decisions — a smaller model is fine).

## Option A — Ollama (recommended, all platforms)

```bash
# macOS: brew install ollama   |   Windows/Linux: https://ollama.com/download
ollama serve
ollama pull qwen2.5:14b        # writer (sweet spot) — or qwen2.5:32b if you have RAM
ollama pull qwen2.5:7b         # judge (optional, faster decisions)
```
`.env`: `LOCAL_LLM_BASE_URL=http://localhost:11434/v1`, `LOCAL_LLM_MODEL=qwen2.5:14b`
On Apple Silicon, Ollama uses Metal automatically — no GPU setup needed.

## Option B — LM Studio (Mac/Windows)

1. Download LM Studio, load an instruct model (Qwen 2.5 / Llama 3.1, 14B+).
2. Developer tab → Start Server (default port 1234).
`.env`: `LOCAL_LLM_BASE_URL=http://localhost:1234/v1`

## Option C — llama.cpp server (any platform, CPU ok)

```bash
llama-server -m model.gguf --port 8080 -c 8192
```
`.env`: `LOCAL_LLM_BASE_URL=http://localhost:8080/v1`

## Option D — vLLM / custom gateway (Linux + GPU)

Any server exposing `/v1/chat/completions` works, including multi-model
gateways with a separate decision endpoint (`/v1/decide`) for the judge role:
set `JUDGE_MODE=decide` in `.env` if your gateway supports it.

## Model guidance (measured in production)

- **<7B models**: usable only with the full rewrite loop; expect most drafts
  to land 55–70/100 on the retention rubric on the first attempt.
- **14B–32B instruct**: the sweet spot — drafts at 65–85, loop reaches 90+.
- **Quantization matters**: very aggressive quants (Q1–Q2) degrade instruction
  following (word budgets, format rules). Q4_K_M or better recommended.
- The judge call is short and cheap; speed beats size there.

## Voice (TTS)

Piper runs on CPU everywhere. Download a voice from the Piper voices
repository (e.g. `es_MX-claude-high` for Spanish, `en_US-amy-medium` for
English) into `assets/voices/` and point `tts.voice` in `config.yaml` at it.
Calibrate `tts.speed` so measured speech lands at your target words/minute —
the QC gate checks **real audio duration**, not the nominal setting.
