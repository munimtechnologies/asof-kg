# Prescription drug labels with no prescribing text (2026-10-14)

Status: **preliminary**. The counts below come from openFDA count queries that anyone can re-run. One label was checked down to its SPL XML on DailyMed. A full per-label audit (`audits/hollow_spl.py`, job `hollow-spl-v1`) is queued. It sorts every such label by kind and checks whether the same company publishes the text under another label, and it will replace these numbers.

## What we found
While auditing boxed warnings ([label-sync-2026-10-14.md](label-sync-2026-10-14.md)), four labels that looked stale turned out to be empty. Their structured product labels (SPLs) hold the product data, the bottle label and an empty "SPL MEDGUIDE" heading. They have no indications, no dosage, no warnings and no boxed warning. One is Zydus Lifesciences Limited's levofloxacin tablets label (set id ffa121b8-388f-4d7b-af48-d4aa8d9b5961, version 11, updated 2024-08-16, ANDA077652, NDCs 65841-691/-692/-693). Its SPL XML on DailyMed has four sections:

| LOINC | Section | Content |
|---|---|---|
| 48780-1 | SPL product data elements | strengths, ingredients, imprints ZC55-ZC57 |
| 42231-1 | SPL MEDGUIDE (two) | empty `<text/>` |
| 51945-4 | Package label, principal display panel | "Levofloxacin Tablets USP, 250 mg ... Rx only" and bottle images |

Other levofloxacin labels carry the fluoroquinolone boxed warning (tendon rupture, peripheral neuropathy, CNS effects, myasthenia gravis). It is the only levofloxacin label from any Zydus company in openFDA.

## How common it is
openFDA drug label endpoint, data last updated 2026-10-13. Query: product type HUMAN PRESCRIPTION DRUG, with `indications_and_usage`, `dosage_and_administration`, `warnings_and_cautions` and `warnings` all missing.

- **1,138 of 35,865** prescription labels have none of these sections.
- **Most are expected:** medical gases, whose labeling has no prescribing information in this form (oxygen 442, nitrogen 129, nitrous oxide 41, carbon dioxide 36, air 35, helium 16, plus mixtures). Blood-collection anticoagulant solutions are another group (Fenwal, Inc. 37).
- **One drug company stands out: Zydus Lifesciences Limited, with 205 of its 265 prescription labels (77%)** (116 dated 2024, mostly in August and November-December). They span 168 generic names. Some of these drugs carry boxed warnings on other labels, such as levofloxacin, tofacitinib and febuxostat. Others need a Medication Guide or carry known serious risks, such as isotretinoin, lenalidomide, methotrexate, bosentan and ambrisentan; whether each has a boxed warning elsewhere is what the full audit checks.
- **The sister US company is complete:** Zydus Pharmaceuticals USA Inc. has 179 prescription labels in openFDA, and none of them is empty. For tofacitinib, a full Zydus extended-release label with the boxed warning is also in openFDA; for levofloxacin, no Zydus company has one.
- NuCare Pharmaceuticals, Inc. (a repackager) has 10 such labels. The rest are scattered.

Queries, for example:
- `https://api.fda.gov/drug/label.json?search=openfda.product_type:"HUMAN PRESCRIPTION DRUG"+AND+_missing_:indications_and_usage+AND+_missing_:dosage_and_administration+AND+_missing_:warnings_and_cautions+AND+_missing_:warnings&count=openfda.manufacturer_name.exact`
- the same with `+AND+openfda.manufacturer_name.exact:"Zydus Lifesciences Limited"` and `&count=openfda.generic_name.exact&limit=1000`
- `https://dailymed.nlm.nih.gov/dailymed/services/v2/spls/ffa121b8-388f-4d7b-af48-d4aa8d9b5961.xml`

## Why it matters, and what it does not show
- DailyMed and openFDA are where clinicians, pharmacists, apps and researchers look up labels, and where drug knowledge graphs get them. An empty SPL shows a prescription drug with no warnings, and any tool that reads "no boxed_warning field" as "no boxed warning" will be wrong for these products.
- It does not show that patients got no information. The paper insert in the bottle may be complete. The empty SPL may be a filing or conversion error, and the text may sit in a document that did not reach DailyMed. NLM publishes SPLs as companies submit them and does not review their content.
- We found no published count of prescription SPLs that carry no prescribing text. FDA's own review of SPL formats (PLR vs. older layout) and studies of label differences between manufacturers (Duke et al. 2013, PMID 23042584) look at labels that have text.

## Next
- Run the full audit (`hollow-spl-v1`). For each empty drug label, it checks whether the drug carries a boxed warning on other labels and whether any company in the same family has a full label.
- Hand-check a sample on DailyMed, then report the list once, factually, to the labeler and to DailyMed/FDA's SPL contacts.

Research data, not medical advice. Made by MV2 of Munim, Inc. with AI agents (Claude) working in his name. Text CC BY 4.0.
