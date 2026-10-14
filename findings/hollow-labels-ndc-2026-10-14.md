# Addendum: the empty prescription labels belong to products FDA lists as marketed (2026-10-14)

MV2 of Munim, Inc., with AI agents (Claude) working in his name. Research data, not medical advice. Text and data CC BY 4.0; code Apache-2.0.

This adds one check to [hollow-labels-2026-10-14.md](hollow-labels-2026-10-14.md), which found 222 human prescription drug labels (SPLs) in openFDA/DailyMed with no indications, dosage, warnings or boxed-warning text, 205 of them from Zydus Lifesciences Limited.

## What was checked

For each of the 222 labels, a sealed job (ndc-lookup-v1, 2026-10-14) took every product NDC on the label (529 in all) and:

1. asked DailyMed's web service (`/services/v2/spls.json?ndc=`) which labels carry that NDC, and
2. looked the NDC up in FDA's NDC Directory bulk file (`download.open.fda.gov/drug/ndc/drug-ndc-0001-of-0001.json.zip`), recording marketing category, start and end dates and listing expiry.

The re-run of the label scan in the same job reproduced the published counts exactly (35,865 prescription labels, 1,023 with no prescribing text, 222 drug labels, 205 from Zydus Lifesciences).

## Result

| | NDCs | Labels |
|---|---|---|
| Product NDCs on the 222 empty labels | 529 | 222 |
| NDCs for which DailyMed returns only the empty label | 529 | 222 |
| NDCs listed in FDA's NDC Directory | 524 | |
| ... with no marketing end date on or before 2026-10-14 (still marketed) | 524 | |
| Zydus Lifesciences Limited NDCs | 488 (487 in the Directory) | 205 |
| NDCs on empty labels of boxed-warning drugs | | 78 labels |

- **Searching DailyMed by the NDC on the package leads only to the empty label**, for all 529 NDCs. This is expected, since an NDC belongs to one labeler's listing, but it means someone holding one of these packages and looking it up by NDC does not reach prescribing text from that listing.
- **524 of the 529 NDCs are current listings in FDA's NDC Directory that have not reached a marketing end date.** 518 have no end date at all (listing expiry 2026-12-31 or 2027-12-31). Six have a planned end date between 2026-10-15 and 2028-12-31: four Vantive dialysis-solution NDCs listed as unapproved drugs for use in a drug shortage, and two Zydus trazodone NDCs. So these are not stale records of withdrawn products: by FDA's own listing data they are products on the market.
- The five NDCs not in the Directory are three torsemide NDCs (Sarfez Pharmaceuticals), one peritoneal dialysis solution (Vantive US Healthcare) and one dimethyl fumarate NDC (Zydus Lifesciences).

The full table (set id, labeler, generic name, NDC, DailyMed result, NDC Directory status and dates) is [hollow-labels-ndc-2026-10-14.csv](hollow-labels-ndc-2026-10-14.csv).

## Limits

- The NDC Directory reflects what labelers list; a listed product may not be shipping. Paper inserts packed with the products may be complete; this audit sees only the electronic labels.
- The same caveats as the main finding apply: openFDA says its data are unvalidated, and the labels may have been filed this way or lost text in conversion. We do not know which.

## Reported

The main finding was sent once to DailyMed/NLM support (with FDA's SPL address in copy) and once to Zydus's medical-affairs and drug-safety addresses on 2026-10-14. NLM opened a support case and said to expect a reply in 2 to 5 business days.
