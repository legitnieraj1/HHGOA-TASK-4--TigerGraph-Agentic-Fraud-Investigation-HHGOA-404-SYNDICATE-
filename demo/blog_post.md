# Building an agentic fraud investigator on TigerGraph

We built an agent for the TigerGraph × Hacker House Goa fraud investigation challenge: given an alert (a
risk-score spike, a customer complaint, or an analyst's tip), it investigates a graph of 590,742 card
transactions, decides what kind of fraud it's looking at (if any), gathers more evidence when it isn't sure,
recommends what the bank should do under an approval-gated policy, and writes the case back into the graph so
the next investigation can find it.

## The one rule that shaped everything

The brief was explicit: *the LLM reasons, it doesn't detect.* Every fraud signal, every probability, every
policy decision in our pipeline is deterministic Python running against the graph. The LLM is called exactly
once per case -- to write the plain-language summary and the SAR narrative, over evidence that's already been
assembled and decided. We kept that separation because it's the only way to make an agent an analyst can
actually trust: if the model doesn't decide, its mistakes are text-generation mistakes, not silent false
negatives on a $10,000 fraud.

## Card ID wasn't a column

First real problem: the dataset's cases reference cards like `C12382-K1`, but `transactions.csv` has no
`card_id` field -- only a `customer_id` and Vesta's anonymized `card1`-`card6` columns, and `card1` turned out to
be a 1:1 alias for the customer, not the card. We had to reverse-engineer the actual rule from the 5,565 closed
cases: the card suffix is the dense rank of `card6` (credit/debit) per customer, NULLs first. Validated against
all 14,955 closed-case transaction links: zero mismatches. Small thing, but nothing downstream works without it.

## The bank's own risk score was actively misleading

We expected `risk_score` to be a strong feature. On the closed-case population it's *inverted*: fraud-vs-cleared
AUC of 0.058. Cleared (false-alarm) cases average a risk score of 0.88; confirmed fraud cases average 0.47. The
README warned us -- "never treat it as the answer" -- and it wasn't kidding. We trained a calibrated propensity
model on the closed-case labels instead (OOF AUC 0.947), and even that model turned out to be *blind* to two of
the five patterns: in-person account-takeover and out-of-region fraud look almost identical to normal behaviour
in Vesta's engineered features. We had to blend the propensity model with graph-pattern confidence, weighted
per pattern by how much we could actually trust each signal -- and document exactly where each one goes blind,
rather than pretend one model covers everything.

## Memory that measurably helps

Account-takeover and out-of-region use are not separable from a single episode's transaction shape -- we
confirmed that with a decision tree that couldn't beat 67% either way. What *did* help: the pattern history on
the same card. Held out 1,580 confirmed-fraud cases with a prior fraud case on the same card, and case memory
alone moved pattern-classification accuracy from 50.9% to 75.3%. That's not a marginal effect -- it's the
difference between a coin flip and a genuinely useful call, and it only exists because the closed cases are
memory the agent can actually query, not a static training set.

## A deterministic simulator can still lie to itself

The dataset doesn't give you real customer replies to a validation request -- you have to simulate them. Our
first version tied the simulated response to the agent's *own* current probability estimate, which sounds
reasonable until you realize it's circular: a step-up-auth check with a binary confirm/deny split at 0.30 meant
any case the pattern classifier was even mildly suspicious of got treated as an outright denial, which then
*became* the evidence that justified blocking. We only caught it because a case with a genuinely borderline
probability (0.32) came back "confirmed fraud" after the fix nudged it, and the reasoning didn't hold up under
a second look. Fixed by widening the simulated response to a real three-way split (confirm / inconclusive /
deny) instead of a hard cutoff, and by never letting a settled response collapse different underlying evidence
strengths to the same fixed number. Worth saying out loud: none of these bugs showed up by reading the code.
They only showed up by actually running cases and checking whether the output made sense.

## What TigerGraph specifically bought us

- **Native vector search**, so policy clauses, typologies, and 5,565 closed-case summaries live as embeddings on
  the same vertices the graph queries already touch -- no separate vector database, and a query can combine a
  graph traversal with a similarity search in one call.
- **Installed GSQL queries** for pattern detection that would be painful in plain SQL: a sliding-window
  card-testing detector, a device-ring scan across the whole graph via degree centrality, structuring detection,
  all running server-side.
- **MCP**, so the same 12 installed queries plus generic GSQL and vector tools are available to any LLM client
  without us writing a bespoke tool-calling layer.

## What we'd improve with more time

A real UI panel for live, multi-turn tool-calling demos (Gemini 3's OpenAI-compatible endpoint breaks on
multi-turn tool calls -- a real, undocumented-as-far-as-we-found gotcha that cost us a debugging session before
we switched to the native SDK). Deeper regulatory grounding: we fetched and read two of the fifteen listed
regulatory references directly rather than fabricate their content, and indexed the rest as pointers only --
more time would mean reading all fifteen. And R7 (disputed charge matches a recurring pattern) can never fire
in our implementation, because the dataset has no merchant identity, only a product category code -- a real
gap we chose to document rather than paper over with a guess.

*[TODO: screenshots, live demo link, submission link]*
