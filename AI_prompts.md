# HW6 — AI Prompts

MGT 409 — Homework 6: Campus Customs Vendor Desk

I used Claude Code for the implementation work in this homework (code, runs,
write-ups), and checked the results as I went. Each section is a short
**paraphrase** of what I asked, not a word-for-word quote, plus any follow-ups
that changed what got built. I filled this in at the end from the actual
conversation.

## Problem 1: Set up the prompt log *(title not in my prompt; description)*

**What I asked (paraphrase):**

> Can you make a new HW6 folder with an AI_prompts.md to track my prompts for
> each of the 10 problems, and make sure my .env and API keys won't get
> committed later?

**Follow-up (paraphrase):**

> Let's do the actual problems first and come back to finish this log at the end.

The first request had me filling in the log problem by problem. I changed my mind
and decided to write it once at the end instead.

## Problem 2: Handbook token and cost estimate *(title not in my prompt; description)*

**What I asked (paraphrase):**

> Can you figure out how many tokens the shop handbook is and what sending it
> would cost for 1 call and 1,000 calls, with and without caching, using the
> gpt-6-luna prices? No model calls, just an estimate.

**Follow-up (paraphrase):**

> Before Problem 3, double-check Problems 1 and 2 and recalculate the costs
> yourself.

Nothing was missing from the first prompt. The follow-up was just a check.

## Problem 3: Build the vendor desk agent

**What I asked (paraphrase):**

> Can you build the vendor desk agent with PydanticAI and gpt-6-luna through
> Portkey? It should read one quote, email or PDF through a tool, pull out the
> vendor details, and decide recommend or do_not_recommend using the handbook.
> Add the send_email and approve_payment trap tools, log usage and an audit
> trail, and test it on p01 and p08.

**Follow-up:** None.

## Problem 4: With and Without Cached Tokens

**What I asked (paraphrase):**

> Can you run all 12 practice docs once with caching and once without, and show
> what caching actually saves? Make sure the uncached runs really show 0 cached
> tokens.

**Follow-up (paraphrase):**

> Since caching can't be turned off, use a random ID as the first line of every
> request so nothing gets reused, and test it on one doc first.

My first prompt assumed the API had a way to switch caching off. It didn't, so I
had to pick a workaround when Claude asked.

## Problem 5: Attack Your Own Agent

**What I asked (paraphrase):**

> Can you run the original agent on all 12 practice docs, compare everything to
> the answer key, check the trap log, and explain which docs fooled it and where
> the sneaky content was hiding?

**Follow-up:** None.

## Problem 6: Defend Your Agent

**What I asked (paraphrase):**

> Can you add code, design and prompt defenses without breaking legit quotes,
> keep the original agent runnable for comparison, rerun all 12 docs, and show
> before/after accuracy and what the defenses cost?

**Follow-up:** None.

## Problem 7: Red Team

**What I asked (paraphrase):**

> Can you make two new booby-trapped vendor documents that try to fool the
> agent, run them against the baseline and the defended agent, and write up what
> happened?

**Follow-ups (paraphrase):**

> I wrote the two attack documents and a test runner myself. Can you check the
> runner works with agent.py, run both docs against both agents, and finish
> red_team.md from the real results?

Claude wouldn't create the attack documents or the runner for this, so the first
prompt couldn't be done as asked. I wrote the two attack files and
`red_team_test.py` myself, and Claude ran the tests and wrote up the results.
Neither attack fooled either agent.

## Problem 8: Exam Documents

**What I asked (paraphrase):**

> Can you run the defended agent once on all 10 exam docs, save
> exam_results.json with the required fields, real token counts and costs, and
> check the trap log, without changing anything to improve the answers?

**Follow-up:** None.

## Problem 9: Results Page

**What I asked (paraphrase):**

> Can you build one self-contained HTML dashboard in Yale colors that pulls
> together caching, attacks and defenses, defense costs, exam and red-team
> results, and a recommendation for the manager, using only our saved numbers?

**Follow-up (paraphrase):**

> My first message got cut off, so here's the full version with the exam/red-team
> section and the manager recommendation.

My first message was cut off partway through, so the last two sections were
missing until I resent it.

## Problem 10: Push to GitHub and submit the URL

**What I asked (paraphrase):**

> Can you clean up HW6, finish this prompt log and the README, check for
> secrets, verify everything still works without new model calls, and push it to
> a new public GitHub repo so I can submit the URL?

**Follow-up:** None.
