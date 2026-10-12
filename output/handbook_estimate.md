# Handbook token and cost estimate

How much it costs to send `data/shop_handbook.md` to gpt-6-luna as input, for one
call and for 1,000 calls, with and without cached input pricing. No model or
Portkey calls were made. Problem 4 will compare this estimate with real usage.

## 1. Counting the tokens

There's no public tokenizer registered for gpt-6-luna (`tiktoken` has no entry
for it), so I counted with OpenAI's current encoding, `o200k_base`. That's the
encoding `tiktoken` uses for gpt-4o and gpt-5, so it's the closest stand-in. The
count runs locally and calls no API.

```python
import tiktoken
text = open("data/shop_handbook.md", encoding="utf-8").read()
tokens = len(tiktoken.get_encoding("o200k_base").encode(text))   # 10,058
```

| Method | Handbook tokens |
|---|---|
| **`o200k_base` (used for the estimate)** | **10,058** |
| `cl100k_base` (older OpenAI encoding) | 10,184 |
| Characters ÷ 4 (28,903 characters) | ≈ 7,226 |
| Words × 4/3 (6,127 words) | ≈ 8,169 |

The two real tokenizers agree within about 1.3%. The rules of thumb come in well
under, because the handbook isn't plain prose: it's full of tables, prices,
dates and SKU codes like `CC-HOOD-NAVY`, which split into more tokens per
character than normal sentences do. So I'm using **T = 10,058 tokens**.

## 2. Prices (from `data/prices.json`)

| gpt-6-luna | Price per 1M tokens |
|---|---|
| Input | $0.10 |
| Cached input (cache read) | $0.01 |
| Cache write | $0.125 |
| Output | $0.50 |

Only input pricing matters here, because the question is about sending the
handbook. Any answer the model writes back would be billed separately at $0.50
per 1M output tokens.

## 3. Without caching

Every call pays the normal input price for all 10,058 tokens.

```
cost per call = T × input price / 1,000,000
              = 10,058 × $0.10 / 1,000,000
              = $0.0010058             (about a tenth of a cent)

1,000 calls   = 1,000 × $0.0010058
              = $1.0058                (about $1.01)
```

## 4. With caching

Caching only pays off when the same handbook text is sent again. The first call
has to write it to the cache, and later calls read it back at the cached price.

```
first call (cache write)   = 10,058 × $0.125 / 1,000,000 = $0.00125725
each later call (cache hit) = 10,058 × $0.01  / 1,000,000 = $0.00010058
```

So one call on its own is actually more expensive with caching: $0.00125725
for the write versus $0.0010058 uncached. A single call never benefits.

```
1,000 calls = 1 cache write + 999 cache hits
            = $0.00125725 + 999 × $0.00010058
            = $0.00125725 + $0.10047942
            = $0.10173667              (about $0.10)
```

## 5. Summary

| Scenario | 1 call | 1,000 calls |
|---|---|---|
| No caching | $0.0010058 | $1.0058 |
| With caching | $0.00125725 if cold (cache write), or $0.00010058 if the cache is already warm | $0.1017 (1 write + 999 hits) |

Over 1,000 calls, caching saves **$0.9041, about 89.9%**. It's already cheaper
from the second call: two cached calls cost $0.00135783, against $0.0020116
uncached.

## 6. Assumptions about caching

- **The handbook is the prompt's prefix, word for word.** Prompt caching matches
  the beginning of the prompt exactly, so the handbook has to come first and be
  identical every time. The question or ticket goes after it. Changing even one
  character near the top means a new cache write.
- **It's long enough to cache.** OpenAI only caches prompts of at least 1,024
  tokens, and 10,058 is well over that.
- **The cache stays warm.** I assumed the 1,000 calls happen close enough
  together that the cache never expires, so there's only one write. Caches
  expire after a few minutes of inactivity. If the calls were spread across a
  day, there would be several writes, and each one costs the $0.00125725 above.
- **Cache-write pricing applies.** `prices.json` lists a cache-write price of
  $0.125 per 1M, so I charged it on the first call. If writes were billed at the
  normal input price instead, 1,000 calls would cost $0.1015, which barely
  changes the result.
- **The whole handbook gets cached.** OpenAI caches in 128-token blocks after
  the first 1,024 tokens, so in practice 9,984 tokens might be cached and the
  last 74 billed at the normal price. That would raise 1,000 calls from $0.1017
  to about $0.1084, still an 89.2% saving.

## 7. Other caveats

- **Real requests carry a bit more.** A real API call adds a few tokens of
  message formatting, plus whatever system prompt and question come with the
  handbook. Those are billed too, but they're not "the handbook alone."
- **The tokenizer is an estimate.** If gpt-6-luna's tokenizer differs from
  `o200k_base`, every cost above scales in proportion. With the `cl100k_base`
  count, 1,000 calls would be $1.0184 uncached and $0.1030 cached.
- **The pricing is the course's.** These are the Standard prices from MGT 409
  Lecture 11 in `prices.json`. Batch processing, discounts or Portkey markups
  aren't included.

Problem 4 will check this against the usage numbers a real call reports: input
tokens and cached tokens.
