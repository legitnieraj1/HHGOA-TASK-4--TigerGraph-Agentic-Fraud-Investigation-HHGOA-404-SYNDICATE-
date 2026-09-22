# Regulatory guidance (grounded excerpts)

Two of the regulatory references from the README were fetched and read directly (2026-09-22); the rest are
indexed as reference pointers only (title + what they cover), since the full PDFs weren't fetched. Do not
treat the pointer-only entries as verbatim source text in a citation -- cite the grounded ones for content,
the pointers only to name what a rule area is called.

## FinCEN: Guidance on Preparing a Complete & Sufficient SAR Narrative (source for `sar.narrative`)

A SAR narrative must identify five essential elements plus the method of operation: **who** (conducted the
activity: occupation, role, known relationships if more than one suspect), **what** (the instruments/mechanisms
used -- for card fraud this is the card, the compromised credentials, or the device/account used to route
purchases), **when** (first noticed and duration; individual transaction dates and amounts, never a table or
pre-formatted spreadsheet -- SAR systems do not render them; give aggregated totals alongside the individual
dates/amounts, not instead of them), **where** (which accounts, which institutions if any are external, any
foreign jurisdiction involved), and **why** (what about the activity is unusual for this customer, compared to
their normal pattern and to similar customers). **How** (modus operandi) describes concisely and in a logical
order how the suspect activity was carried out -- for a card-testing-then-purchase pattern, this means stating
the sequence explicitly: the testing transactions, then the larger purchase, with amounts and the gap between
them.

Organize the narrative as three parts: an **introduction** (the type of suspicious activity, e.g. card testing
or account takeover; any prior SAR on the same subject; whether OFAC/SDN screening is relevant; a summary of
the red flags that triggered the report), a **body** (the supporting facts: parties involved, unusual patterns,
the money movement in chronological order), and a brief **conclusion**. Keep it concise and chronological.

## FinCEN: Advisory on Account Takeover Activity (FIN-2011-A016)

Red flags: unusual ATM activity, clustered ACH transactions across different geographic areas, sudden wire
transfers, and changes to customer/account profile information, often following credential compromise via
malware, spyware, or a similar attack on the customer's device. File a SAR using "account takeover fraud" in
the narrative; on the SAR form, mark "computer intrusion" if the vector is known, "wire transfer fraud" /
"account takeover fraud - ACH" for the channel used, and "identity theft" when PINs or account numbers were
accessed without authorization. This directly matches this dataset's `account_takeover` pattern: mixed-channel
activity and device/match-flag anomalies pointing to compromised credentials rather than a stolen card number.

## Reference pointers (title/agency only; not fetched for content)

- **FinCEN SAR Filing FAQs (Oct 2025)** -- procedural questions on when/how to file.
- **Preparing a Complete and Sufficient SAR Narrative (2003 predecessor edition)** -- superseded by the guidance
  above; same subject.
- **FinCEN SAR Supporting Documentation (FIN-2007-G003)** -- what backs up a SAR filing internally (this dataset's
  `case.evidence[]` plays that role).
- **SAR Activity Review: Trends, Tips and Issues** -- periodic bulletin of typologies; general background.
- **FinCEN Advisory on Imposter Scams and Money Mule Schemes** -- relevant to fan-out money movement, not directly
  to the five patterns in this dataset's closed-case history.
- **FinCEN Identity-Related Suspicious Activity (2021)** -- relevant to `card_not_present_new_device` and the
  device-ring `undocumented` pattern (identity/device compromise indicators).
- **FATF: Illicit Financial Flows from Cyber-Enabled Fraud** -- typology background for card fraud generally.
- **FATF: Money Laundering Using New Payment Methods / Professional Money Laundering / Remittance & Currency
  Exchange / Trade-Based ML / International Co-operation** -- money-laundering typologies broader than card
  fraud; background only for this dataset.
- **FFIEC: Money Laundering and Terrorist Financing Red Flags** -- general red-flag checklist, overlaps with the
  advisories above.
- **FFIEC: Suspicious Activity Reporting** -- BSA compliance program requirements around SAR filing, not narrative
  content.
- **OFAC: Specially Designated Nationals list** -- screening list; check subjects against it before filing, not a
  narrative-content source.
