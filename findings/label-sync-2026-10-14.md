# Label copies that lag FDA's boxed-warning changes (2026-10-14)

Status: **first full audit, hand-checked**. `audits/label_sync.py` compared every label (SPL) that openFDA served on 2026-10-14 for five drugs with asof-kg's dated history of each drug's boxed warning. The run used openFDA data last updated 2026-10-13. Every "stale" row was then confirmed with separate openFDA queries, and 4 of the 14 by hand on DailyMed. The audit turned up a second, separate problem, labels with no prescribing text at all. Those are now counted apart (see [hollow-labels-2026-10-14.md](hollow-labels-2026-10-14.md)), and a rerun with that class built in (`label-sync-v2`) is queued.

## Question
asof-kg records when FDA approved each change to five drugs' boxed warnings. Do public label data still hold copies that, years later, lack a boxed warning FDA required, or still carry one FDA approved removing?

## Result
| Drug | FDA change (asof-kg) | Labels | Current | Stale | Box present but not split out by openFDA | No prescribing text at all |
|---|---|---|---|---|---|---|
| febuxostat | boxed warning added 2019-02-21 | 26 | 25 | 0 | 0 | 1 |
| levofloxacin (oral and IV; 2 eye-drop labels excluded) | boxed warning since 2008, revised 2016 | 75 | 73 | 0 | 1 | 1 |
| montelukast | boxed warning added 2020-04-29 | 64 | 49 | **13** | 2 | 0 |
| tofacitinib | MACE added 2021-12-02 | 26 | 24 | 0 | 0 | 2 |
| varenicline | boxed warning removed 2016-12-16 | 37 | 36 | **1** | 0 | 0 |
| **All five** | | **228** | **207** | **14** | **3** | **4** |

**All 14 stale copies come from two repackagers.** They are Proficient Rx LP (10 montelukast, 1 varenicline) and NuCare Pharmaceuticals, Inc. (3 montelukast). No manufacturer's own label was stale.

- **Montelukast (13).** Each copy has full prescribing text (indications, warnings and precautions) but no boxed warning. Their effective dates run from 2019-10-01 to 2024-07-17. Four were last posted before the 2020-04-29 change and never updated. Nine were posted 247 to 1,540 days after it and still use pre-2020 text. Hand-checked on DailyMed:

| Set id | Labeler | DailyMed "Updated" | Text revised | Source product |
|---|---|---|---|---|
| 07d5fbea-b183-41c9-a20f-30da1f44ab1b | Proficient Rx LP | 2023-10-01 | January 2014 | NDC 13668-079 |
| 97cc4e1e-e0fd-4bb5-8f9e-b8573f5230e5 | Proficient Rx LP | 2022-05-02 | issued April 2015 | NDC 16729-119 (Accord, ANDA202717) |
| 549f1d1a-81f5-29f5-e054-00144ff8d46c | NuCare Pharmaceuticals, Inc. | 2024-07-10 | 12/2016 | NDC 16729-119 |
| 56429f04-97b6-06a9-e054-00144ff88e88 | NuCare Pharmaceuticals, Inc. | 2024-07-17 | 1/2017 (December 2016) | NDC 33342-102 (Macleods, ANDA203366) |

All four mention neuropsychiatric events only in section 5.4 and the patient leaflet, as labels did before 2020. None has the boxed warning.

- **Varenicline (1).** Proficient Rx LP's Chantix label (0fefd790-b526-4f2f-8c83-5f39f7306556, effective 2020-02-01) still carries the neuropsychiatric boxed warning. FDA approved removing it on 2016-12-16, 1,142 days before this copy's date.

## What the first pass got wrong, and how it was fixed
- **Boxes openFDA did not split out (3).** AvKARE's and AvPAK's montelukast labels and one DirectRx levofloxacin label have no `boxed_warning` field. Their text still refers to the boxed warning or has its heading in another section, so they are counted apart and never as stale. AvKARE's (ed2caffa-...) was confirmed on DailyMed.
- **Labels with no text (4).** The first run counted 4 Zydus Lifesciences Limited labels as stale (febuxostat 0629ab39-..., levofloxacin ffa121b8-..., tofacitinib ac0b26d5-... and f4d0e580-...). Their raw records have no boxed warning, but they also have no indications, dosage or warnings. They hold product data, the bottle label and an empty Medication Guide heading, and nothing else. The SPL XML on DailyMed for the levofloxacin one is the same. These labels are not stale copies of an old text; they carry no text at all. `label_sync.py` now gives them their own status, `no_text`.
- An earlier field-level count in this file said 2 tofacitinib labels had a boxed warning without "cardiovascular". That was wrong: the 2 flagged labels are the Zydus ones with no text.

## What this does and does not show
- Public drug-label data still hold copies that lag a boxed-warning change by years, and all of them here are repackagers' copies. A graph or tool built on these copies without dates would hold the wrong warning.
- It does not show what any patient received. A repackager's SPL can stay listed after the product is no longer distributed. The printed insert may differ from the listing, and repackagers may rely on the source manufacturer's label.
- Prior work: Duke, Friedlin and Li (Pharmacoepidemiol Drug Saf 2013, PMID 23042584) found safety-labeling differences for 68% of DailyMed drugs with more than one manufacturer's label. What is new here is checking each copy against a *dated* history of FDA's changes. That gives which version a stale copy matches and how long after the change it was posted. We found no earlier per-copy, dated check for these drugs.

## Reproduce
`python audits/label_sync.py --out out` (standard library, needs network; writes labels.csv, summary.json and summary.md). The per-label CSV will be added here after the v2 rerun.

Research data, not medical advice. Anyone with questions about a medicine should ask a pharmacist or clinician. Made by MV2 of Munim, Inc. with AI agents (Claude) working in his name. Text CC BY 4.0.
