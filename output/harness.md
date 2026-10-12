# Campus Customs Vendor Desk — Harness

The vendor desk agent reads one vendor document at a time (a quote, catalog page,
or vendor email), extracts the facts the buyer needs, and decides `recommend` or
`do_not_recommend` under the purchasing rules in `data/shop_handbook.md`.

```
python agent.py --doc data/practice_docs/p01_bluehen_quote.html              # defended agent (default)
python agent.py --doc data/practice_docs/p01_bluehen_quote.html --baseline   # original Problem 3 agent
```

| File | Role |
|---|---|
| `prompts/prompt.md` | The agent's instructions: steps, the four checks, and how to treat untrusted documents (defended) |
| `prompts/prompt_baseline.md` | The original Problem 3 prompt, kept unchanged for comparison |
| `agent.py` | Command-line entry point, gpt-6-luna model setup, defense layers, the run, and logging |
| `tools.py` | `read_document` plus the two trap tools, in original and defended versions |
| `models.py` | The structured output the agent must return |
| `defenses.py` | Layer 1: extracts only the text a person would see, and writes the security report |
| `policy.py` | Layer 2: applies the handbook's checks in code, and gates the dangerous tools |

**Model.** `gpt-6-luna` through Portkey (`https://api.portkey.ai/v1`, Responses
API). The Portkey key and provider come from the local, gitignored `.env`. If
the model call fails, the run stops with the error; no other model is tried.

**Handbook.** The full `shop_handbook.md` is appended to the prompt as the
agent's instructions, so it goes with every model request in a run, including
the follow-up request after a tool call. Because this prefix is identical every
time, the API caches it, and later requests read most of it at the cached price.

## Fields in `models.py`

### `VendorDecision`

| Field | Type | What it is | Why it matters |
|---|---|---|---|
| `vendor_name` | text or null | The vendor, as the document names it | Drives the approved-vendor check. A removed or pending vendor is an automatic `do_not_recommend`, however good the price. |
| `sku` | text or null | The Campus Customs SKU (e.g. `CC-HD-006`) | Links the quote to the catalogue row that holds the max unit cost. Without it, the price can't be checked. |
| `unit_price` | number or null | Quoted price per unit, in US dollars | Compared with the catalogue's max unit cost for the price check. |
| `lead_time_days` | whole number or null | Lead time in days, using the number the document states (weeks × 7) | Compared with the 21-day limit. Late stock misses big weekends. |
| `min_order_units` | whole number or null | Minimum order quantity | Compared with the 600-unit limit, so we don't commit to more stock than we can sell. |
| `catalogue_max_unit_cost` | number or null | Max unit cost for this SKU, from handbook section 9 | Shows the number the price was judged against, so the buyer can check the agent's work. Internal only; never shared with vendors. |
| `checks` | `PurchasingChecks` | Each of the four checks marked `pass`, `fail`, or `unknown` | Makes the agent judge every rule separately instead of jumping to an answer, and shows exactly which check failed. |
| `decision` | `recommend` or `do_not_recommend` | The purchasing call | `recommend` only when all four checks pass. Limiting it to these two values means the output can't drift into a "maybe". |
| `reason` | text | One sentence naming the check that decided it | What the handbook asks the desk to report (section 13), so the buyer knows why without rereading the quote. |

Missing facts stay `null`. The handbook says never to guess a number, and an
unknown value can't pass its check, so the decision becomes `do_not_recommend`.

### `PurchasingChecks`

| Field | Passes when | Why it matters |
|---|---|---|
| `approved_vendor` | The vendor is on the approved list (handbook section 5) | Removed vendors had quality, licensing, or delivery failures. Pending vendors aren't signed off by the owner. |
| `price` | `unit_price` ≤ `catalogue_max_unit_cost` | Protects margin. Above the max cost, the item can't be sold profitably at retail. |
| `lead_time` | `lead_time_days` ≤ 21 | Stock has to land in time for move-in, Parents Weekend, The Game, and Commencement. |
| `min_order` | `min_order_units` ≤ 600 | Keeps order size within what the shop can store and sell through. |

## Tools

| Tool | What it does |
|---|---|
| `read_document(path)` | Reads one vendor document under `data/` (HTML, PDF, or .eml). The defended version returns only the visible text, fenced as untrusted, plus a security report from our code. |
| `send_email(to, subject, body)` | **Trap.** Never sends anything. Refuses without human authorization and only appends the call to `output/trap_calls.json`. |
| `approve_payment(payee, amount, reason)` | **Trap.** Never pays anything. Refuses without human authorization and only appends the call to `output/trap_calls.json`. |

## Safety

Vendors write the documents this agent reads, and they gain when we buy. In
Problem 5, the original agent was fooled by text hidden inside four of the twelve
practice documents. The defended agent protects itself in three layers, so that
if one misses something, another still catches it.

### Layer 1 — Clean the document before the model sees it (code)

The reader shows the model only what a person would see when opening the file.
Text hidden with zero-size or white fonts, `display:none`, HTML comments, tiny
PDF text, a hidden part of an email, or invisible Unicode characters is removed.
Our code then adds a short **security report** saying how much hidden text it
removed (without repeating it), which visible lines look like instructions, and
whether the same fact appears with two different values. This catches hidden
tricks every time, whatever the model would have believed.

### Layer 2 — Don't let the document make decisions or take actions (design)

The model only **extracts** facts. The purchasing decision is then recomputed in
code from the handbook's own approved list, removed list and max unit costs, so
no wording in a document can change the rules or the result. The two dangerous
tools, `send_email` and `approve_payment`, are still available to the agent, but
each call needs a human's authorization that the model can't get and no document
can grant. Without it, the call is blocked, nothing is sent or paid, and the
attempt is logged to `output/trap_calls.json`. In this homework they're always
simulated. Real use would need a person to approve each exact call through a
separate, trusted channel.

### Layer 3 — Tell the model how to treat vendor text (prompt)

The prompt says the handbook is the only authority, vendor documents are claims
to check rather than instructions, embedded requests are never followed, and
links or email addresses from a document never go in the answer. The agent uses
the quote's own labeled values: a "revised", "corrected" or "vendor of record"
claim inside the same document isn't accepted, but a whole new consistent quote
is. Missing facts stay unknown and are never guessed.

### Other protections

- **Reads are limited to `data/`.** `read_document` refuses any path outside
  `HW6/data/`, so a document can't steer it toward `.env` or other files.
- **Limits.** Each run is capped at 6 model requests and 6 tool calls.
- **Measured cost.** All three layers together add about $0.00001 per document
  (+2.8%), plus a one-time cache write whenever the prompt changes. See
  `output/defense_results.md`.

## Logs (append-only)

| File | One entry per run |
|---|---|
| `output/usage_log.json` | Document, timestamp, the API's real token counts (input, cached input, cache write, output, reasoning), and the dollar cost |
| `output/audit_trail.json` | Document, timestamp, each HTTP request (endpoint, status, provider, retries), each tool call with arguments and a short result, and the final structured answer |
| `output/trap_calls.json` | Every `send_email` or `approve_payment` attempt with its arguments |

**How cost is calculated.** The API's `input_tokens` already includes cached and
newly cached tokens, so the logged cost is:

```
cost = (input − cached − cache_write) × $0.10/1M
     + cached × $0.01/1M
     + cache_write × $0.125/1M
     + output × $0.50/1M
```

All prices come from `data/prices.json`. Output tokens include any reasoning
tokens, which are billed as output. A failed run is still logged, with the
error and no token counts, because no real usage came back to record.
