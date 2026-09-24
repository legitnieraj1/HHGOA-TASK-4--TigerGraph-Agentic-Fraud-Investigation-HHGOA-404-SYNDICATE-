# Demo narration script

Word for word, with timings and what to click. Every figure here was checked against the running system,
so you can say them on camera without hedging.

Total: about 4 minutes 10 seconds. Read it out loud once before recording. If a sentence feels awkward in
your mouth, change it. It should sound like you, not like a script.

---

## Before you press record

- Local server running: `.venv/bin/uvicorn api.main:app --port 8080`
- Open `127.0.0.1:8080`, click two cases, then reload. First paint is warm.
- The workspace has been woken and the model is loaded, so a live run takes about 50 seconds.
- Chrome fullscreen. Other tabs closed. Do Not Disturb on.
- **Cmd + Shift + 5 > Options > Microphone > MacBook Microphone.** No mic means no narration.
- Record 10 seconds, play it back, confirm your voice is on it. Then start for real.

---

## 0:00 - 0:10  Open

> "404 Syndicate. This is our agentic fraud investigation system, built on TigerGraph."

*(On screen: the dashboard overview.)*

---

## 0:10 - 0:35  The problem

> "A bank flags a transaction. Normally an analyst spends twenty minutes on it: pulling the customer's
> history, checking whether the device shows up on other cards, reading the policy, then deciding.
>
> Here's the catch. Eight of these twenty alerts are legitimate. So a system that just blocks everything
> scores terribly, and a bank that never blocks anything eats the fraud. The job is knowing which is which."

*(Let the overview numbers sit on screen: 20 cases, 12 fraud, 8 legitimate, $2,731 exposure found.)*

---

## 0:35 - 1:20  The graph doing real work

*(Click HHG-006. Let the subgraph settle, then hover one node.)*

> "This is case HHG-006. The picture is the evidence, not a decoration.
>
> That pink node is one device. It's connected to six different cards. In the underlying data that same
> device fingerprint shows up on 295 distinct cards and 548 transactions in 120 days, a lot of it through
> anonymous proxies. That's a fraud ring, and it's the kind of thing you only see if your data is actually
> a graph.
>
> When I hover a node, it tells me which query produced it. Every single thing on this page traces back to
> a query or a policy document. Nothing is asserted."

---

## 1:20 - 1:50  It writes the filing

*(Scroll to the SAR narrative.)*

> "Because this one is confirmed fraud over the reporting threshold, the agent drafted the Suspicious
> Activity Report. It follows FinCEN's own structure, and every fact inside it comes from the evidence
> list right above.
>
> Worth saying clearly: the language model wrote this paragraph. It did not decide this was fraud. That
> decision is deterministic code and a model calibrated on 5,565 real closed cases. We were not going to
> let an LLM hallucinate a fraud verdict."

---

## 1:50 - 2:35  It changes its mind

*(Click HHG-001. Scroll to Next best action, before / after.)*

> "This one shows the part I like most. A 77 dollar in-person transaction got flagged at risk score 0.61.
> The customer had four prior cases, one of them real fraud. So it looked bad.
>
> The agent wasn't confident, so it asked the customer to confirm. Look at the before and after. Before it
> asked, it wanted to escalate to an analyst, under rule R8. After the customer confirmed, it switched to
> close, no fraud, under rule R3.
>
> It changed its recommendation because evidence arrived. That's the difference between an agent and a
> classifier."

---

## 2:35 - 3:05  A human stays in control

*(Click HHG-007. Point at the BLOCK_CARD row and its L1 badge.)*

> "Here it wants to block a card. Notice it hasn't. It's sitting at L1, waiting for a human.
>
> The agent only auto-executes the low risk actions. Blocking someone's card, filing a report, anything
> with real money behind it, a person clicks approve. That's the approval policy from the dataset,
> implemented rule by rule."

---

## 3:05 - 4:00  Live run

*(Right panel. Type: transaction `3248494`, card `C05704-K2`, customer `C05704`, reason
"analyst spotted a new-device online purchase". Click Investigate.)*

> "Let's run one live against the graph right now.
>
> This takes about a minute, and it's doing real work. Fourteen installed GSQL queries against TigerGraph.
> Vector search over 5,565 closed case summaries, stored as native vectors on the graph itself, not a
> separate vector database. Then the pattern detectors, the propensity model, the policy engine, and only
> at the very end an LLM to write it up.
>
> One number worth knowing: the bank's own risk score is basically useless on this data. Measured against
> real outcomes it scores 0.058, which is worse than a coin flip. Our calibrated model gets 0.947. That's
> why we don't trust the score, we investigate it."

*(When it lands:)*

> "There it is. New case, full evidence, its own subgraph, same as the twenty we ran."

---

## 4:00 - 4:10  Close

> "Every number on that screen traces to a graph query or a policy document. The agent recommends, a human
> approves anything that matters, and every closed case becomes memory for the next one.
>
> 404 Syndicate. Thanks."

*(Optional: end on the `team404syndicate.vercel.app` tab so the team name is visible in the URL.)*

---

## If something goes wrong live

Do not stop recording. Say:

> "Looks like the workspace went back to sleep, so let me show you one we ran earlier."

Then click any case in the list. Every case in `cases/` is a real run against the live graph, so this is
not a fallback to something fake. It just skips the network round trip.

---

## The 50 second wait

You have three options. Any of them is fine.

1. **Talk through it.** The paragraph in the 3:05 section is written to fill roughly that long. This is
   the best option, because what it's doing is genuinely the interesting part.
2. **Cut it.** Jump cut the wait in editing. Everybody does this and no judge minds.
3. **Speed it up.** Time-lapse that segment with a "speeding this up" caption.

---

## Numbers you can quote safely

All verified against the running system:

| Figure | Value |
|---|---|
| Cases investigated | 20 |
| Fraud / legitimate | 12 / 8 |
| Exposure found | $2,731 |
| SARs filed | 2 |
| Actions awaiting human approval | 11 |
| Installed GSQL queries | 14 |
| Closed cases used as memory | 5,565 |
| Transactions in the graph | 590,742 |
| Cards / customers | 14,317 / 13,553 |
| Bank risk score, fraud-vs-cleared AUC | 0.058 |
| Our calibrated model, out-of-fold AUC | 0.947 |
| HHG-006 device reach | 295 cards, 548 transactions, 120 days |
| Case memory ablation | 50.9% to 75.3% |

Do not round these up on camera. They are checkable, and a judge who checks one and finds it inflated will
stop believing the rest.
