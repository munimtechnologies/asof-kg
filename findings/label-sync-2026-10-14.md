# Label copies that lag FDA's boxed-warning changes: a first look (2026-10-14)

Status: **preliminary**. The counts come from openFDA count queries you can re-run (links below). The individual labels were checked by hand on DailyMed. A full per-label audit script (`label_sync.py`) is being run and will replace these counts.

## Question
asof-kg records when FDA approved each change to five drugs' boxed warnings. Does the public label data still contain copies that do not reflect a change years later? These would be copies that lack a boxed warning FDA required, or that still carry one FDA approved removing.

## Data
openFDA drug label endpoint (`api.fda.gov/drug/label.json`), last updated 2026-10-13, queried on 2026-10-14. Each label (SPL set) appears once. openFDA itself says its data are unvalidated.

| Drug | FDA change (asof-kg) | Labels in openFDA | Flagged by field-level query | What the flag means |
|---|---|---|---|---|
| varenicline | boxed warning removed 2016-12-16 | 37 | 1 still has a boxed warning | still carries the removed warning |
| montelukast | boxed warning added 2020-04-29 | 64 | 15 have no `boxed_warning` field | may lack the required warning |
| febuxostat | boxed warning added 2019-02-21 | 26 | 1 has no `boxed_warning` field | may lack the required warning |
| tofacitinib | MACE added to the boxed warning 2021-12-02 | 26 | 2 have a boxed warning without "cardiovascular" | may lack the 2021 addition |
| levofloxacin (oral and IV) | boxed warning since 2008, revised 2016 | 75 route entries | 2 have no `boxed_warning` field, but their text cites "[see Boxed Warning]" | probably a parsing gap, not a stale label |

Queries, for example:
- `https://api.fda.gov/drug/label.json?search=openfda.generic_name:varenicline+AND+_exists_:boxed_warning&count=openfda.manufacturer_name.exact`
- `https://api.fda.gov/drug/label.json?search=openfda.generic_name:montelukast+AND+_missing_:boxed_warning&count=set_id`
- `https://api.fda.gov/drug/label.json?search=openfda.generic_name:tofacitinib+AND+boxed_warning:cardiovascular&count=openfda.manufacturer_name.exact`

## What a field-level count gets wrong
A missing `boxed_warning` field does not prove that a label lacks the warning. Of three flagged montelukast labels checked on DailyMed:

| Set id | Labeler (repackaged label) | DailyMed "Updated" | Text dated | Boxed warning on DailyMed |
|---|---|---|---|---|
| 07d5fbea-b183-41c9-a20f-30da1f44ab1b | Proficient Rx LP (source NDC 13668-079) | 2023-10-01 | manufacturer text revised January 2014 | **none** |
| 549f1d1a-81f5-29f5-e054-00144ff8d46c | NuCare Pharmaceuticals, Inc. (source NDC 16729-119) | 2024-07-10 | highlights revised 12/2016 | **none** |
| ed2caffa-a75c-1c27-ae30-2d8280eaea7d | AvKARE (source NDCs 62175-204, -205) | 2025-12-16 | highlights revised 10/2025 | present ("WARNING: SERIOUS NEUROPSYCHIATRIC EVENTS"), but filed outside openFDA's `boxed_warning` field |

So two of the three were posted more than three years after FDA required the boxed warning on 2020-04-29, and they still carry pre-2020 text without it. The third has the warning; openFDA did not split it out. The varenicline copy (set id 0fefd790-b526-4f2f-8c83-5f39f7306556, effective 2020-02-01) still shows the boxed warning removed on 2016-12-16. `check_copy()` in asof-kg flags it.

## What this does and does not show
- It shows that copies of label text in public drug-label data can lag FDA's safety changes by years. It also shows that a graph built from them without dates would hold the wrong warning.
- It does not show what any patient received. A repackager's SPL can stay listed after the product is no longer distributed. The printed insert may differ from the listing, and repackagers may be relying on their source manufacturer's label.
- Label discrepancies across manufacturers are a known problem (Duke, Friedlin and Li, Pharmacoepidemiol Drug Saf 2013, PMID 23042584, reported safety-labeling differences for 68% of DailyMed drugs with more than one manufacturer's label). What is new here is checking each copy against a *dated* history of FDA's changes. That gives which version a stale copy matches and how long after the change it was posted. We found no earlier per-copy, dated check for these five drugs.

## Next
- Run `label_sync.py` over every label of the five drugs. It treats a box found outside the `boxed_warning` field as "unparsed", never as stale. Then publish the per-label table (CSV) with the counts.
- Add more drugs whose boxed warnings were added or removed on known dates.

Research data, not medical advice. Anyone with questions about a medicine should ask a pharmacist or clinician. Made by MV2 of Munim, Inc. with AI agents (Claude) working in his name. Text CC BY 4.0.
