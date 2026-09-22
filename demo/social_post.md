# Social post draft (X / LinkedIn, Nieraj's voice)

Built a fraud investigation agent on @TigerGraphDB for the Hacker House Goa challenge and learned more from the
dataset fighting me than from anything that went smoothly.

first real problem wasn't the agent, it was the data. the case files reference card ids that literally don't
exist as a column anywhere. had to reverse-engineer the actual rule from 5,565 closed cases and validate it
against every single one before I trusted it.

second one's better: the bank's own fraud risk score is basically useless on this dataset. checked it against
the confirmed outcomes and it's *inverted* -- the false alarms score higher on average than the actual fraud.
so much for "just use the risk score."

the part I'm most into though: gave the agent memory. it can look up prior cases on the same card, and just
that alone took pattern-classification accuracy from a coin flip to 75% on held-out cases. not a vibes
improvement, an actual measured one.

also learned the hard way that a "simulated customer response" can accidentally become circular evidence if
you're not careful -- had a case confirm itself into fraud because the simulator's decision depended on the
same probability it was supposed to be updating. fun bug to trace.

whole thing runs on TigerGraph's native vector search for policy + case memory, GSQL queries doing actual
pattern detection (device rings, card testing, structuring) instead of asking an LLM to eyeball it, and the LLM
only ever writes the explanation -- never decides. felt like the right split once I actually built it.

more in the writeup: [link] / demo: [link]

@TigerGraphDB
