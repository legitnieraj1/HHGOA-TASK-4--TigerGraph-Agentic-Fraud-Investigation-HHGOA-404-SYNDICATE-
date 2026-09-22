"""Chunk the policy/typology/regulatory markdown (data/policy/*.md, extracted verbatim from the dataset README
in Phase 0, plus two grounded FinCEN excerpts fetched in Phase 4 -- see data/policy/regulatory_guidance.md)
into named chunks for the vector store. Chunk ids are stable and human-legible so an evidence citation can read
`ref: "policy:R5"` directly, matching the answer format's "cite the rule number" requirement (policy s.7)."""
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]
POLICY_DIR = ROOT / "data" / "policy"


def _mk(chunk_id, source, section, title, text):
    text = text.strip()
    return {"chunk_id": chunk_id, "source": source, "section": section, "title": title, "text": text}


def chunk_fraud_policy():
    text = (POLICY_DIR / "fraud_policy.md").read_text()
    chunks = []
    # ### N. Title sections, each up to the next ### or end. Rules (R1-R10) are pulled OUT of "### 3. Rules"
    # into their own chunks; everything else stays as one chunk per section.
    parts = re.split(r"\n(?=### )", text)
    for part in parts:
        m = re.match(r"### (\S+)\. (.+?)\n", part)
        if not m:
            continue
        num, title = m.group(1), m.group(2)
        body = part[m.end():]
        if num == "3":  # Rules: split R1..R10 out individually (R10's bold markup has no trailing period, unlike R1-R9)
            for rm in re.finditer(r"\*\*(R\d+)\. ([^*]+?)\*\*\.?\s*(.+?)(?=\n\*\*R\d+\.|\Z)", body, re.S):
                rid, rtitle, rtext = rm.group(1), rm.group(2).rstrip("."), rm.group(3).strip()
                chunks.append(_mk(f"policy:{rid}", "fraud_policy.md", f"3.{rid}", rtitle,
                                  f"Rule {rid} ({rtitle}). {rtext}"))
            continue
        chunks.append(_mk(f"policy:{num}", "fraud_policy.md", num, title, f"Policy section {num} ({title}). {body}"))
    return chunks


def chunk_known_patterns():
    text = (POLICY_DIR / "known_patterns.md").read_text()
    names = ["card_testing", "card_not_present_fraud", "card_not_present_new_device", "out_of_region_use", "account_takeover"]
    chunks = []
    for i, m in enumerate(re.finditer(r"\*\*(\d)\. ([^*]+?)\.\*\*\s*(.+?)(?=\n\n\*\*\d\.|\Z)", text, re.S)):
        n, title, body = m.group(1), m.group(2), m.group(3).strip()
        chunks.append(_mk(f"pattern:{names[int(n) - 1]}", "known_patterns.md", n, title,
                          f"Fraud pattern '{names[int(n) - 1]}' ({title}). {body}"))
    return chunks


def chunk_regulatory():
    text = (POLICY_DIR / "regulatory_guidance.md").read_text()
    chunks = []
    parts = re.split(r"\n(?=## )", text)
    ids = ["reg:sar_narrative", "reg:ato_advisory", "reg:pointers"]
    for part, cid in zip((p for p in parts if p.startswith("## ")), ids):
        m = re.match(r"## (.+?)\n", part)
        title = m.group(1)
        body = part[m.end():]
        chunks.append(_mk(cid, "regulatory_guidance.md", cid.split(":")[1], title, f"{title}. {body}"))
    return chunks


def chunk_misc():
    chunks = []
    for name, cid, title in [("things_to_know.md", "ref:things_to_know", "Things to know"),
                             ("glossary.md", "ref:glossary", "Glossary")]:
        body = (POLICY_DIR / name).read_text()
        chunks.append(_mk(cid, name, "misc", title, body))
    return chunks


def all_chunks():
    return chunk_fraud_policy() + chunk_known_patterns() + chunk_regulatory() + chunk_misc()


if __name__ == "__main__":
    cs = all_chunks()
    print(f"{len(cs)} chunks")
    for c in cs:
        print(f"  {c['chunk_id']:26s} ({len(c['text']):4d} chars) {c['title']}")
