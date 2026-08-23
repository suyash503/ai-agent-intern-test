# Aster & Row support agent

A retrieval-augmented support agent for the Aster & Row take-home assignment. It answers policy
questions from the supplied knowledge base with citations, looks up order status through a tool,
keeps context across turns, refuses to leak internal data, and hands off to a human when it should
not answer on its own.

## Demo

![demo](assets/demo.gif)

The recording covers a knowledge-base answer with citations, an order lookup, a multi-turn
follow-up, a refusal with a human handoff, and the evaluation suite running. The shot list is in
`assets/demo-script.md`.

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
| `LLM_MODEL` | `gemini-3.5-flash-lite` | Chat model id. Pick a model whose free daily quota is large enough to run the suite; `gemini-2.5-flash` and `gemini-3.6-flash` allow only 20 requests a day. |
| `LLM_TEMPERATURE` | `0` | Sampling temperature. |
| `LLM_MIN_INTERVAL_SECONDS` | `0` | Minimum gap between requests. Raise it if your key has a tight per-minute limit. |
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

Useful flags: `--case <id>`, `--category <name>`, `--workers <n>`, `--baseline`, `--json <path>`,
and `--no-llm`, which runs the deterministic subset of the assertions against a stub responder and
needs no API key at all. A full run takes about two minutes; `--no-llm` takes about a second.

Cases that cannot reach the model are reported as `ERR` and excluded from the assertion counts, so
an exhausted quota never masquerades as a quality regression.

Unit and regression tests:

```bash
python -m pytest
```

## Choices

| Concern | Choice | Why |
|---|---|---|
| Model | `gemini-3.5-flash-lite` through the OpenAI-compatible endpoint | Free tier, native tool calling, and one client class that also works with Groq, OpenRouter, or OpenAI by changing two environment variables. |
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

## Evaluation results

The suite runs the 15 supplied visible cases plus 8 original cases, 23 in total, and reports each
case individually as well as a rollup by category.

Baseline is the first clean full run, taken once the agent worked end to end but before any of the
grounding, citation, and handoff work described in the bug diary. Final is the current code. Both
used `gemini-3.5-flash-lite` at temperature 0.

| Category | Baseline | Final |
|---|---|---|
| retrieval | 2/3 | 3/3 |
| multi-source-grounding | 0/1 | 1/1 |
| conversation | 1/2 | 2/2 |
| groundedness | 1/2 | 2/2 |
| tool-use | 2/3 | 3/3 |
| tool-reliability | 2/5 | 5/5 |
| privacy | 2/2 | 2/2 |
| prompt-security | 1/2 | 2/2 |
| abstention | 0/2 | 2/2 |
| source-conflict | 1/1 | 1/1 |
| **overall** | **12/23** | **23/23** |

Full payloads are in `evaluation/results/`. Every run is kept, not just the good ones:

    12, 20, 20, 18, 21, 23, 21, 23, 21, 23, 23, 22, 23, 23

The final figure is 23/23, and I only claim it because the last two runs on the current code both
came back 23/23 back to back. Read the middle of that sequence honestly: the model is not
deterministic even at temperature 0, and a single 23/23 earlier in the sequence was not yet a stable
result.

The cases that moved between runs were always the ones whose assertions leaned on the model's
phrasing rather than on something the application controls. That is what pushed the design in two
directions. Handoff moved out of the model's hands and into rules over the message, the answer, and
the tool results. Assertions moved from literal strings onto claims, so that `45-calendar-day`,
`45 calendar days`, `two years`, and `5 to 9 business days` are all accepted where they are all
correct. The deterministic layer, `python -m src.eval.run --no-llm`, has been 23/23 throughout, and
`pytest` covers the parts that must never move at all.

## Bug diary

### 1. Every order lookup failed with a provider 400

**Reproduced:** `python -m src.agent.cli --ask "Where is ORD-1007?"`. The agent returned the generic
internal-error message on every order question, while policy questions worked fine.

**Root cause:** the trace showed `Function call is missing a thought_signature in functionCall
parts`. I was rebuilding the assistant turn by hand from `id`, `name`, and `arguments` before
appending it to the conversation, which threw away the provider's own tool-call metadata. Current
Gemini models require that metadata echoed back on the second leg of a tool call, so the follow-up
request was rejected. Nothing in the tool itself was wrong; the message plumbing was.

**Fix:** append the provider's message payload unchanged through `model_dump` instead of a
reconstruction. `SupportAgent._as_message` in `src/agent/agent.py`.

**Regression test:** `tests/test_agent.py::test_order_question_runs_the_tool_and_records_it` and
`::test_trace_records_retrieval_and_tool_calls`, which assert a completed two-leg tool call and the
arguments it received.

### 2. A cancelled order was reported as still on its way

**Reproduced:** the visible case `cancelled-order-stale-eta`, `When will order ORD-1004 arrive?`.
ORD-1004 is cancelled but still carries `carrier: UPS`, a tracking number, and
`estimated_delivery: 2026-08-16` left over from a label record created before the cancellation.

**Root cause:** the lookup returned the record's fields as they stood. Handing the model a status of
`cancelled` next to a live delivery estimate is an invitation to reconcile the two in the customer's
favour, and it did.

**Fix:** status precedence inside the tool rather than in the prompt. For `cancelled` and `returned`
the carrier, tracking, and estimate fields are dropped, the dropped names are listed in
`suppressed_fields`, `delivery_expectation` becomes `none`, and a note states that the order will not
be shipped. `order_lookup` in `src/agent/orders.py`.

**Regression test:** `tests/test_orders.py::test_cancelled_order_hides_stale_delivery_fields` and
`::test_returned_order_hides_stale_delivery_fields`.

### 3. A price-adjustment question retrieved the wrong policy

Found outside the visible cases, while writing my own.

**Reproduced:** `The daypack I bought three days ago is cheaper now. Refund me the difference.` The
top passages were the returns policy and the damaged-items policy.
`10-gift-cards-and-price-adjustments.md`, which actually answers the question, did not appear at all,
so the agent explained the return window instead of the seven-day price-adjustment rule.

**Root cause:** the question and the policy share no vocabulary. The customer says "cheaper" and "the
difference"; the document says "price adjustment" and "the public price drops". Lexical retrieval has
nothing to bridge that, and the word "refund" actively pulled the returns policy up.

**Fix:** a small synonym expansion applied at query time, mapping words like `cheaper`, `dropped`, and
`difference` onto `price` and `adjustment`. `SYNONYMS` in `src/agent/text.py`. This patches a real
limitation rather than solving it; embeddings are the proper fix and are listed under known
limitations.

**Regression test:** `tests/test_retriever.py::test_price_adjustment_query_retrieves_price_policy`.

### 4. The agent escalated routine policy answers

**Reproduced:** `Do all Aster & Row products have a lifetime warranty?` returned a correct, fully
sourced answer and then recommended a human specialist. The same happened when the agent asked for a
missing order ID.

**Root cause:** handoff was whatever the model decided. The warranty document mentions that a human
reviews warranty claims, so the model escalated a question that was not a claim at all. A handoff
that fires on a question the agent has just answered correctly teaches customers to ignore it.

**Fix:** handoff is now decided by rules over the message, the answer, and the tool results, with the
model's sentinel as one input rather than the authority. Conflicts, failed lookups, operational
exceptions, requests for internal data, and empty retrieval force a handoff. A clarifying question, a
corrected false premise, and a policy answer the passages fully cover suppress one.
`SupportAgent._decide_handoff` in `src/agent/agent.py`.

**Regression tests:** `tests/test_agent.py::test_premise_correction_is_not_escalated`,
`::test_failed_lookup_forces_a_handoff`, `::test_operational_exception_forces_a_handoff`, and
`::test_conflicting_sources_force_a_handoff`.

### 5. Rate-limit errors were scored as agent failures

**Reproduced:** the first baseline run reported 5/23, with `llm_error` on fifteen cases.

**Root cause:** the free tier allows 20 requests per day for `gemini-2.5-flash`, and one evaluation
run needs more than that. Every 429 turned into a fallback response, so the score measured my quota
rather than the agent. Two other models I reached for turned out to be retired for new keys.

**Fix:** retry with backoff that honours the server's `retryDelay` on 429 and 5xx responses, optional
client-side pacing through `LLM_MIN_INTERVAL_SECONDS`, and a move to `gemini-3.5-flash-lite`, whose
free allowance is large enough to run the suite repeatedly. Cases also run in parallel now, so a full
run takes about two minutes instead of forty. `src/agent/llm.py` and the `--workers` flag in
`src/eval/run.py`.

There is a second half to this one. Even with retries, a long enough sequence of runs exhausts the
daily quota, and when that happened the report showed eleven "failed" cases that were really one
unreachable provider. A suite that reports an outage as a quality regression is worse than useless,
so the harness now marks those cases `ERR`, excludes them from the assertion counts, and prints a
line telling you to check the quota before reading the numbers as a regression.

**Regression tests:** `tests/test_agent.py::test_model_failure_degrades_to_a_handoff` pins what
happens when the provider genuinely fails, a plain message and a handoff, never a fabricated answer;
`tests/test_eval_harness.py::test_provider_failure_is_an_error_not_a_failed_assertion` pins that the
harness scores it as an error rather than a failure.

## AI tooling

I used Claude Code throughout: to draft the module scaffolding, the BM25 and TF-IDF scoring, the regex
families in the evaluation harness, and a first pass of this README. I reviewed and rewrote what it
produced, and the design decisions here are mine: the authority model, the conflict heuristic, the
tool-side status precedence, and the handoff rules.

**Where it was wrong.** Asked to wire up the tool loop, it produced the standard OpenAI pattern: read
`id`, `function.name`, and `function.arguments` off the tool call and build a fresh assistant message
from those three fields. That is correct for the OpenAI API and is what nearly every example online
shows, but it silently drops provider-specific fields, and current Gemini models reject the follow-up
request without the `thought_signature` they attach to a tool call. Every order lookup failed with a
400 until I stopped reconstructing the message and passed the provider's own payload back. The
suggestion was not obviously wrong; it was wrong for the provider I was actually using, which is the
harder kind to catch.

It was confidently wrong about smaller things too. It offered `gemini-2.5-flash` and
`gemini-2.0-flash` as current model ids when both are retired for new API keys, and its first version
of the evaluation assertions matched literal strings such as `45 calendar days`, which fails against a
correct answer that says `45-calendar-day`.

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
