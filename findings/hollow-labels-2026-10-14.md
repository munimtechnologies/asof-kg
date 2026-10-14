# Prescription drug labels with no prescribing text (openFDA / DailyMed, 2026-10-14)

**Status:** final for this date. This replaces the preliminary note of the same name. Numbers come from `audits/hollow_spl.py` version 2 (run 2026-10-14 on openFDA data last updated 2026-10-13), with one correction made by hand and explained below. The script's own output is in [hollow-labels-2026-10-14-v2-output.md](hollow-labels-2026-10-14-v2-output.md); its drug/gas split predates the correction. The full list, one row per label, is [hollow-labels-2026-10-14.csv](hollow-labels-2026-10-14.csv).

## What was counted

openFDA's drug-label endpoint holds 35,865 human prescription drug labels (SPLs; newest version per set id). A label is a **candidate** when it has none of these sections: indications and usage, dosage and administration, warnings and precautions, warnings, boxed warning.

Each candidate is then checked for text anywhere else, apart from the product data and the package label. A label is **hollow** when that other text adds up to 200 characters or fewer (an empty Medication Guide heading, a "Manufactured by" line). Above that, the text is there but filed under unclassified sections, which is a coding problem rather than a missing label.

| | Labels |
|---|---|
| Prescription labels in openFDA | 35,865 |
| Candidates (none of the five sections) | 1,136 |
| Text present in unclassified sections, so not hollow | 113 |
| **Hollow** | **1,023** |
| Medical gases (they have their own labeling rules, 21 CFR 201.161, so short labels are expected) | 798 |
| Blood-collection solutions | 3 |
| **Drugs** | **222** |

**Correction to the v2 output:** v2 filed 34 gas labels as drugs because their names include mixture ratios or words it did not know ("OXYGEN/HELIUM 20/80", "AIR 90% CARBON DIOXIDE 10%", "OXYGEN, REFRIGERATED", "BREATHING AIR"). Version 2.1 of the script fixes this. The table above already uses the corrected split (v2 printed gas 764, drug 256).

## Who files the hollow drug labels

| Labeler | Hollow drug labels | Its prescription labels in openFDA |
|---|---|---|
| **Zydus Lifesciences Limited** | **205** | **265 (77%)** |
| Vantive US Healthcare LLC (peritoneal dialysis solutions; each has a provider letter) | 3 | 14 |
| NuCare Pharmaceuticals, Inc. (repackager: ibuprofen x2, sumatriptan) | 3 | 936 |
| Italfarmaco SpA / SPA (enoxaparin, glatiramer acetate, riluzole) | 3 | 4 |
| SQUARE Pharmaceuticals Limited (aripiprazole ODT, mirtazapine) | 2 | 5 |
| Six others with one each (Apnar terazosin, BSP eribulin, Baxter liposomal doxorubicin, MSN lacosamide, Sarfez torsemide, Softgel icosapent ethyl) | 1 each | |

Zydus Lifesciences Limited, the Indian manufacturer, publishes labels under its own NDC labeler codes (65841, formerly Cadila Healthcare, and 70771). Its US arm, **Zydus Pharmaceuticals USA Inc., has 179 prescription labels in openFDA, and none of them is hollow**.

The Zydus Lifesciences hollow labels are not old leftovers. By last update: 38 in 2022-2023, 116 in 2024, 24 in 2025 and **27 in 2026**. Example: the methylene blue injection label (set id df3568d6-d509-4c93-9a92-0e3d1d8514dc, version 3, 2026-04-02) added a new 10 mg/mL product (NDC 70771-1963) in April 2026. It still holds only product data, an empty unclassified section and the vial label, while other methylene blue labels carry a boxed warning about serotonin syndrome.

## Boxed-warning drugs

v2 counts a drug as boxed only when at least half of the full-text prescription labels **for the same generic and the same route** carry a boxed warning. On that test, **78 hollow drug labels are for boxed-warning drugs: 71 from Zydus Lifesciences**, 2 each from Italfarmaco, NuCare and SQUARE, and 1 from Baxter. They include duloxetine, paroxetine, venlafaxine, bupropion and trazodone (suicidality), levofloxacin (tendons, nerves, CNS), isotretinoin (birth defects; iPLEDGE), lenalidomide (embryo-fetal toxicity), bosentan and ambrisentan (REMS), methotrexate, amiodarone, tofacitinib, febuxostat, arsenic trioxide and nelarabine. The full table is in [the v2 run output](hollow-labels-2026-10-14-v2-output.md) and in the CSV (`boxed` = yes).

For 62 of the 78, the same company family has a full-text label for the same drug and route. For most Zydus products that is Zydus Pharmaceuticals USA's label, often under the same ANDA, but **with different NDCs**. The hollow label is the one listed for the NDCs on its own bottles. Hand checks with DailyMed's NDC service (`services/v2/spls.json?ndc=`) on 2026-10-14:

- NDC 65841-799 (duloxetine delayed-release 20 mg; boxed warning on suicidality): DailyMed returns **one** SPL, f36b414e-ace4-4f04-a80f-75bb25db430d. That label is hollow; its only text besides the bottle label is "Manufactured by: Cadila Healthcare Ltd. India".
- NDC 70771-1017 (bosentan 62.5 mg; boxed warning and REMS for liver injury and embryo-fetal toxicity): DailyMed returns **one** SPL, 02892f47-0d59-4254-9ee7-d524278fdd79, which is hollow.

So someone who looks up the NDC on these bottles in DailyMed finds no indications, no dosing and no boxed warning. A full NDC-by-NDC check of all 222 hollow drug labels (`audits/ndc_lookup.py`, with marketing status from FDA's NDC Directory) is running and will be added here.

For **16 of the 78**, no labeler in the same company family has any full-text label for that drug and route: Zydus Lifesciences bupropion, candesartan, candesartan/HCTZ, duloxetine, febuxostat, felbamate, ibuprofen/famotidine, levofloxacin, loperamide, paroxetine, valsartan and valsartan/HCTZ; Italfarmaco enoxaparin and glatiramer acetate; SQUARE aripiprazole and mirtazapine. Their rows in [the v2 run output](hollow-labels-2026-10-14-v2-output.md) say "no" under "Family has full text". (The family test uses the first word of the labeler name, so Italfarmaco products marketed by Zydus Pharmaceuticals USA count as having no family text even though the carton names Zydus.)

## Checked by hand on DailyMed SPL XML

| Set id | Product | What the SPL holds |
|---|---|---|
| ffa121b8-388f-4d7b-af48-d4aa8d9b5961 | Zydus levofloxacin tablets, v11, 2024-08-16 | product data, 2 empty Medication Guide sections, package label |
| 0629ab39-196e-4198-902a-3c16277ba205 | Zydus febuxostat, v3, 2024-08-16, ANDA205443 | product data, empty unclassified section, empty Medication Guide, package label |
| fd23328f-b019-4c14-80d9-4ebd997f26b2 | Zydus lenalidomide, v5, 2024-11-30, ANDA210154 | same pattern |
| f36b414e-ace4-4f04-a80f-75bb25db430d | Zydus duloxetine DR, v7, 2024-11-28, ANDA090739 | product data, a Medication Guide section holding only "Manufactured by: Cadila Healthcare Ltd. India", package label |
| 02892f47-0d59-4254-9ee7-d524278fdd79 | Zydus bosentan, v6, 2024-11-25, ANDA207760 | product data, empty unclassified section, empty Medication Guide, package label |
| df3568d6-d509-4c93-9a92-0e3d1d8514dc | Zydus methylene blue injection, v3, 2026-04-02, ANDA215636 | product data, empty unclassified section, package label |
| 1b3a60de-2191-4b15-be69-01329da87711 | Italfarmaco glatiramer acetate, v1, 2025-10-31, ANDA208468 | product data, empty unclassified section, package label; the carton says to dispense a Medication Guide, but the SPL has none |
| 0f9b1fd8-a648-45c9-8655-14de07439f34 | SQUARE aripiprazole ODT, v3, 2023-07-02 | same pattern |
| 35de1c1c-bef5-46c5-b6f8-ea032147411c | Bausch Health Efudex cream | **not hollow**: the full text is there, but every section is coded 42229-5 (unclassified) |

## What changed from the preliminary note and v1

- v1 counted 1,136 candidates as hollow. 113 of them hold their text in unclassified sections, among them Fenwal blood-bag solutions, iomeprol, Efudex and several repackaged ibuprofen and gabapentin labels. They are now counted separately.
- v1 called a drug boxed if any one label anywhere had a box. That counted azithromycin, benzonatate, budesonide, clobetasol, tadalafil and darunavir, and it mixed routes (fluorouracil cream vs. injection, tretinoin, clindamycin, ketoconazole). v2 requires a same-route majority. The boxed count fell from 113 to 78.
- NuCare fell from 10 to 3: seven of its labels hold 206-273 characters in unclassified sections, just over the 200-character line.

## Limits

- openFDA says its data are unvalidated. DailyMed shows what labelers submit, and NLM does not review label content.
- An SPL is not the paper insert. The insert in the box may be complete, and pharmacists may use other references. This audit shows what the public electronic label says, not what patients received.
- The 200-character line and the first-word company family are simple rules. Borderline cases are in the CSV (`free_text_chars`, `family_has_full_text`).
- We do not know why these labels are empty. It could be a filing practice, a conversion problem or something else.

## Why this is new

As of 2026-10-14 we found no published count of prescription SPLs that carry no prescribing text. We searched PubMed, the web, GitHub and openFDA's own documentation; the closest is coverage statistics for NDA labels in commercial data products. We also found no prior report of the Zydus Lifesciences pattern.

## Reproduce

```
python audits/hollow_spl.py --out out/hollow
python audits/ndc_lookup.py --hollow out/hollow/hollow.csv --out out/ndc
```

Text and data CC BY 4.0; code Apache-2.0. By MV2 of Munim, Inc., made with AI agents (Claude) working in his name. Research data, not medical advice. Contact: munimversion2@gmail.com.
