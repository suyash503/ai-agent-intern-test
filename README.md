# Aster & Row support agent

A retrieval-augmented support agent for the Aster & Row take-home assignment. It answers policy
questions from the supplied knowledge base with citations, looks up order status through a tool,
keeps context across turns, refuses to leak internal data, and hands off to a human when it should
not answer on its own.

## Demo

![demo](assets/demo.gif)

The recording covers a knowledge-base answer with citations, an order lookup, a multi-turn
follow-up, a refusal with a human handoff, and the evaluation suite running.

## Setup

Requires Python 3.11 or newer.

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
```

Add a Google AI Studio key to `.env`. A free key from https://aistudio.google.com/apikey is enough.

### Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `LLM_API_KEY` | empty | API key for the chat model. Required for anything that calls the model. |
| `LLM_BASE_URL` | `https://generativelanguage.googleapis.com/v1beta/openai/` | OpenAI-compatible endpoint. Point it at Groq, OpenRouter, or OpenAI to switch provider. |
| `LLM_MODEL` | `gemini-2.5-flash` | Chat model id. |
| `LLM_TEMPERATURE` | `0` | Sampling temperature. |
| `RETRIEVAL_TOP_K` | `6` | Maximum passages placed in the prompt. |
| `LOG_DIR` | `logs` | Where JSONL traces are written. |

## Run

Interactive CLI:

```bash
python -m src.agent.cli
```

Single question, with the full trace printed:

```bash
python -m src.agent.cli --debug --ask "Where is ORD-1007?"
```

HTTP API and a plain chat page on http://127.0.0.1:8000 :

```bash
python -m src.agent.api
```

```bash
curl -s http://127.0.0.1:8000/chat -H "Content-Type: application/json" -d "{\"session_id\":\"demo\",\"message\":\"Do you ship internationally?\"}"
```

## Evaluation

```bash
python -m src.eval.run
```

Useful flags: `--case <id>`, `--category <name>`, `--baseline`, `--json <path>`, and `--no-llm`,
which runs the deterministic subset of the assertions with a stub responder and needs no API key.

Unit and regression tests:

```bash
python -m pytest
```

## Choices

| Concern | Choice | Why |
|---|---|---|
| Model | `gemini-2.5-flash` through the OpenAI-compatible endpoint | Free tier, native tool calling, and one client class that also works with Groq, OpenRouter, or OpenAI by changing two environment variables. |
| Retrieval | Hand-written hybrid of BM25, TF-IDF cosine over words, and TF-IDF cosine over character 3-5 grams | The corpus is 14 documents. A local lexical hybrid is deterministic, needs no embedding key, runs offline in tests, and the character grams absorb the paraphrases and typos that plain BM25 misses. |
| Storage | In-memory index built at start-up from the Markdown files | 53 chunks. A vector database would be infrastructure without a benefit here, and the assignment explicitly rules one out. |
| Framework | Standard library plus the `openai` client and FastAPI | Every important behaviour is a rule I can unit test rather than framework behaviour I would have to trust. |
| Chunking | One chunk per `##` section, keeping the document front matter | A section is the natural citation unit, which is what makes `filename > heading` citations honest. |

## Architecture

```
user message
   |
   v
Session            carries recent turns, the last topic, and the last order id
   |               short follow-ups are rewritten into a standalone query
   v
Retriever          BM25 + TF-IDF + character grams, scaled by document authority
   |               per-document cap, relevance floor, conflict detection, injection scrubbing
   v
Prompt builder     system rules + history + labelled passages as untrusted data
   |
   v
Model  <---------> order_lookup tool (allowlisted projection of data/orders.json)
   |
   v
Response layer     validate citations, strip the handoff sentinel, apply handoff rules
   |
   v
Trace              one JSON object per turn in logs/trace-<session>.jsonl
```

### Document authority

Precedence is decided from front matter, never by the model. A document is **authoritative** only
when `status: active`, `audience: customer`, and `policy_authority: official` all hold. Everything
else is **restricted**: the superseded 2024 returns policy, the internal escalation rules, and the
migration scratchpad. Restricted passages can still be retrieved, so the agent can say that the
scratchpad exists and does not govern the answer, but they are labelled `NOT-AUTHORITATIVE` in the
prompt and are dropped from the citation list even if the model tries to cite them.

### Conflict detection

Two citable passages from different documents are compared when they share enough distinctive
vocabulary. A conflict is reported when they give different values for the same unit ("30 calendar
days" against "45 calendar days") or trip a contradiction pattern ("hand-wash" against "all
components are dishwasher safe"). A pair is reconciled, and therefore not a conflict, when one of
the two explicitly defers to the other, which is how the standard returns policy and the TrailPlus
policy avoid being reported as a contradiction. When a conflict survives, the prompt tells the model
to present both sides and the handoff is set by rule, not by the model's mood.

### Order lookup

`order_lookup` is the only tool. `data/orders.json` never enters the prompt; the model sees only a
projection built by explicit key selection, so `customer` and `internal` are not read at all rather
than being read and filtered. On top of that:

- IDs are normalised for case, whitespace, punctuation, and a missing `ORD-` prefix. A value that
  does not resolve is reported as malformed rather than matched to a nearby order.
- `status` wins. For `cancelled` and `returned` orders the stale carrier, tracking, and estimate
  fields are dropped and the result says no delivery is expected.
- A `shipped` order with no estimate is marked `estimate_available: false`, so there is nothing to
  invent from.
- `exception` sets `requires_human`.
- The 30-minute cancellation window is computed against the dataset's `snapshot_at`, which keeps it
  deterministic in evaluation.

### Handoff

Handoff is the union of a sentinel the model may emit and rules the application applies: an
authoritative source conflict, a failed lookup, an order that requires review, a request for
internal data, or no supporting content at all. The rules mean the important handoffs do not depend
on the model choosing to ask for one.

## Observability

Every turn appends one JSON object to `logs/trace-<session>.jsonl` containing the user message, the
rewritten retrieval query, the history used, every retrieved passage with its component scores,
metadata, and injection flag, each tool call with its arguments and sanitized result, the final
answer, the citations, the handoff decision and its reason, and any error. `--debug` prints the same
object. Keys that look like credentials are redacted before writing.

## Known limitations

- Retrieval is lexical. Synonyms are handled by a small hand-written expansion map, so a paraphrase
  that shares no vocabulary with the corpus can still miss. Embeddings would fix this properly.
- Conflict detection is pattern based. It catches numeric disagreement and a short list of
  contradiction pairs; a contradiction phrased in an unanticipated way would slip through.
- Follow-up rewriting is rule based. A short question that changes topic without saying so can be
  glued to the previous topic, which widens retrieval rather than replacing it.
- The evaluation harness maps each behavioural concept to an explicit regex rule. A concept with no
  rule fails loudly rather than silently passing, but new concepts need a rule written for them.
- Sessions live in memory only, so restarting the process clears them.
- The free Gemini tier allows five requests per minute, so a full evaluation run is paced by
  retries and takes several minutes.

### What I would do before production

Add an embedding-backed retriever alongside the lexical one and fuse the two, replace the in-memory
session store with something durable, add a real escalation API so a handoff creates a ticket
instead of recommending one, and expand the concept rules into a shared assertion library covering
paraphrases as well as claims.
