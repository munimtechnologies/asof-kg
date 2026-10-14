# asof-kg: clinical knowledge as it stood on any date

Most medical knowledge graphs store facts with no time attached. They cannot tell "what is recommended now" from "what was recommended when the patient was seen", and they quietly use knowledge published later. asof-kg is a small, open prototype that keeps the times apart:

- **Valid time:** when a version (of a guideline, a drug label or a case definition) was in force.
- **Knowledge time:** when it could first be known. The *end* of a version's time in force is known only once its successor is known.
- **Whose knowledge:** the public, or the regulator and the product's sponsor, who often know of a required label change months before it is announced.

Every query takes a `known_at` date and never uses anything known after it. Version 0.3.0, 2026-10-14.

> **Not medical advice.** This is research software and research data. It does not tell anyone what care to get or which medicine to take. Ask a clinician or pharmacist.

## What's in it
| Path | What it is |
|---|---|
| `asofkg/` | Python 3.7+ package, standard library only: as-of queries, consistency checks, leakage metrics, Turtle export, CLI |
| `asofkg/data/uspstf.json` | Care pathways: 8 USPSTF recommendation statements on 3 topics (2008-2024), each with its PMID |
| `asofkg/data/fda_boxed_warnings.json` | Pharmacovigilance: boxed-warning history of levofloxacin, varenicline, montelukast, febuxostat and tofacitinib (14 label versions, 1996-2021), each from FDA approval letters |
| `asofkg/data/cdc_case_definitions.json` | Infectious-disease surveillance: CDC/CSTE Lyme disease case definitions 2011, 2017 and 2022 |
| `asofkg/data/synthetic_*.json` | Made-up encounters and prescription fills for the demos (no real people) |
| `ontology/asofkg.ttl` | OWL 2 ontology built on OWL-Time and PROV-O, aligned to Biolink, MeSH, PATO and RxNorm |
| `shapes/asofkg-shapes.ttl` | SHACL rules for temporal consistency that OWL cannot express |
| `queries/*.rq` | SPARQL competency queries |
| `test_asofkg.py` | unittest suite |

## Run it
```
python -m asofkg demo --known-at 2026-10-13     # care-gap audit: in force then vs newest only
python -m asofkg labels --known-at 2026-10-13   # boxed-warning audit: on the label then vs newest only
python -m asofkg metrics --known-at 2026-10-14  # how often a graph without time answers differently or uses later knowledge
python -m asofkg check                          # consistency report for all three datasets
python -m asofkg ttl --known-at 2018-01-01      # the graph as it could be known on that date
python -m asofkg ttl --known-at 2009-03-01 --view sponsor   # ...as FDA and the sponsor knew it
python -m unittest test_asofkg                  # tests
```

## Measured: what a graph without time gets wrong
`python -m asofkg metrics` asks, on January 1 of every year from 2000 to 2026, which version of each guideline topic, drug label and case definition was in force. It compares the hindsight-free answer with the newest version, which is what a graph built today without time gives for every date. Days before a subject's first version (before a drug was approved, say) are not counted.

| Domain | Queries | Answer changes | Answer rests on later knowledge | Hindsight-free answers using later knowledge |
|---|---|---|---|---|
| Guidelines (USPSTF) | 45 | 34 (76%) | 34 (76%) | 0 |
| Drug labels, by version | 105 | 67 (64%) | 67 (64%) | 0 |
| Drug labels, by boxed-warning content | 105 | 64 (61%) | 67 (64%) | 0 |
| Case definitions (CDC) | 16 | 11 (69%) | 11 (69%) | 0 |
| All three, by version | 166 | 112 (67%) | 112 (67%) | 0 |

- On this grid every changed answer comes from a version that could not yet be known on that day: the static graph's error is all leakage.
- Three answers are right only by luck. For varenicline on January 1 of 2007, 2008 and 2009, the newest label correctly says "no boxed warning", but only because of the 2016 removal; the warning added in 2009 sits in between.
- The tests check that the hindsight-free side never uses later knowledge on a grid of every 11th day from 1996 to 2027, in both the public and the sponsor view.

### Evidence and label changes
Some label changes rest on a trial. asof-kg keeps when the trial report first appeared (PubMed) and when FDA first announced the safety signal, and links the label version to the trial with `prov:wasInfluencedBy`:

| Label change | Took effect | Trial report (PubMed) | Days from report to label | FDA's first signal notice | Days from notice to label |
|---|---|---|---|---|---|
| varenicline: boxed warning removed (EAGLES) | 2016-12-16 | 2016-04-22, PMID 27116918 | 238 | n/a | n/a |
| febuxostat: boxed warning added (CARES) | 2019-02-21 | 2018-03-12, PMID 29527974 | 346 | 2017-11-15 | 463 |
| tofacitinib: mortality and thrombosis added | 2019-07-25 | not yet in a journal | n/a | 2019-02-25 | 150 |
| tofacitinib: MACE added (ORAL Surveillance) | 2021-12-02 | 2022-01-27, PMID 35081280 | **-56** (label first) | 2021-02-04 | 301 |

So evidence can lead labels by most of a year, and labels can lead the journal article: a graph that orders knowledge by publication date alone would get the 2021 tofacitinib change wrong.

## Three domains, one time model
### Care pathways: USPSTF guideline versions
A care-gap audit asks whether a recommended service was missed at a past visit. Done with time, it applies the version in force on the visit date. Done without time, it applies the newest version to every visit. For the 8 synthetic encounters, **5 of 8 verdicts change** when time is ignored, in both directions:

| Encounter | Visit | In force then | Newest version only |
|---|---|---|---|
| E1: colorectal, age 46 | 2019-03-01 | no recommendation (2016 statement starts at 50) | gap (grade B, 2021) |
| E3: breast, woman 42 | 2023-05-01 | ok (grade C, 2016) | gap (grade B, 2024) |
| E5: aspirin, age 55, risk 12% | 2018-06-01 | gap (grade B, 2016) | ok (grade C, 2022) |
| E7: colorectal, age 55 | 2007-06-01 | unknown (no version in this graph yet) | gap (grade A, 2021) |
| E8: colorectal, age 46 | 2021-05-17 | no recommendation (one day before the 2021 statement) | gap (grade B, 2021) |

### Pharmacovigilance: drug-label boxed warnings
A label change has three dates. FDA writes to the sponsor (an FDCA 505(o)(4) letter), often announces the change, and approves the new label later. Every date below is from FDA's approval letters on Drugs@FDA:

| Drug | Sponsor notified | Public | Label changed | Boxed warning after |
|---|---|---|---|---|
| levofloxacin | 2008-07-07 | 2008-07-08 | 2008-10-03 | tendinitis and tendon rupture |
| levofloxacin | 2010-11-15 | 2011-02-25 (no earlier public notice found) | 2011-02-25 | + exacerbation of myasthenia gravis |
| levofloxacin | 2016-05-12 | 2016-05-12 | 2016-07-26 | revised: disabling and potentially irreversible reactions, incl. peripheral neuropathy and CNS effects |
| varenicline | 2009-02-19 | 2009-07-01 | 2009-07-01 | serious neuropsychiatric events |
| varenicline | (sponsor-proposed) | 2016-12-16 | 2016-12-16 | **removed** after the EAGLES trial |
| montelukast | 2020-03-04 | 2020-03-04 | 2020-04-29 | serious neuropsychiatric events |
| febuxostat | (sponsor submitted CARES 2018-01-19) | 2019-02-21 | 2019-02-21 | cardiovascular death |
| tofacitinib | (at approval, 2012-11-06) | 2012-11-06 | 2012-11-06 | serious infections; malignancy |
| tofacitinib | 2019-05-09 | 2019-07-26 | 2019-07-25 | + mortality; thrombosis |
| tofacitinib | 2021-08-23 | 2021-09-01 | 2021-12-02 | + major adverse cardiovascular events |

The 2019 tofacitinib change was approved on July 25 and announced on July 26, so for one day the label in force was not yet public knowledge. asof-kg answers "serious infections and malignancy" for July 25 as known that day, and the new warning once July 26 is reached.

For 11 synthetic prescription fills, **10 of 11 boxed-warning answers change** when only the newest label is used. On 2020-04-01, for example, montelukast's label had no boxed warning yet, but one had been announced on 2020-03-04: asof-kg reports both, and the old label's end date became known 8 weeks before it happened.

**A stale copy in public data.** On 2026-10-14 openFDA's drug label endpoint still served a repackager's Chantix (varenicline) label (set id 0fefd790-b526-4f2f-8c83-5f39f7306556, version 4, effective 2020-02-01) with the neuropsychiatric boxed warning that FDA approved removing on 2016-12-16. A graph built from it without time would assert a warning that was no longer in force. `check_copy()` flags such copies:

```
>>> check_copy(load_labels(), "varenicline", "2020-02-01", copy_has_box=True)
{'expected': 'varenicline-2016', 'consistent': False, 'older': ['varenicline-2009']}
```

### Surveillance: case-definition versions
CSTE adopts a case definition in one year and CDC uses it from the next surveillance year, so here a version is known *before* it takes effect. The 2022 Lyme disease definition (position statement 21-ID-05, spring 2021) changed classification for high-incidence jurisdictions. From mid-2021 a query knows the 2017 definition will end on 2022-01-01; before that, its end is open.

## How time is handled
- **No hindsight:** queries see only versions known by `known_at`. An interval's end is written only once a successor is known. Tests sweep 1996-2026 to check that no answer uses a later source.
- **Coarse dates:** a date given only as a year or month counts as known only once its latest possible day has passed (`Instant`). The Lyme 2017 definition, adopted in "2016", is known from 2016-12-31.
- **Views:** `view="sponsor"` uses the regulator's notice date as knowledge time; `view="public"` uses the announcement.
- **Interval algebra:** `allen()` gives all 13 Allen relations. Consecutive versions must *meet*, and the tests check that.
- **Consistency:** `check()` and the SHACL shapes flag versions that start before the one they replace, cycles, branches, cross-subject supersession, overlapping age bands, notices dated after announcements, and interval ends asserted before any successor exists.

## Ontology notes
- `akg:Version` has three subclasses: `GuidelineVersion` (⊑ `biolink:Publication`), `LabelVersion` and `CaseDefinitionVersion` (⊑ `biolink:InformationContentEntity`). They are pairwise disjoint.
- `akg:supersedes` is asymmetric and irreflexive, and is a sub-property of `prov:wasRevisionOf` and of the transitive `akg:laterVersionOf`.
- `akg:validDuring` is inferred by a property chain (`partOfGuideline` ∘ `inForceDuring`). `RoutineRecommendation`, `RecommendationAgainst` and `LabelVersionWithBoxedWarning` are defined classes a reasoner fills in. `LabelVersionWithoutBoxedWarning` states "no boxed warning" explicitly, since under the open-world assumption a missing risk is not the same as no risk.
- `effectiveFrom`, `announcedOn` and `notifiedOn` hold valid time and the two knowledge times. `notifiedOn` is written only in sponsor-view snapshots. `announcedOn` may fall before or after `effectiveFrom`.
- A label version links to the trial report it rests on with `prov:wasInfluencedBy` (a PubMed record), written only once the version itself is known.
- Drugs are RxNorm ingredients typed `biolink:Drug`; conditions are MeSH terms typed `biolink:Disease`; sex uses PATO.
- Biolink's `temporal_interval_qualifier` is string-valued, so it cannot point at an OWL-Time interval. `akg:inForceDuring` carries the interval and maps to it with `skos:relatedMatch`.
- Dates use `xsd:date`, as OWL-Time's `time:inXSDDate` does. Some OWL 2 DL reasoners need their "ignore unsupported datatypes" option for it.

## Data sources and limits
- USPSTF grades, age bands and dates come from PubMed records (NCBI E-utilities). The `published` date is PubMed's earliest public date, so a boundary may be a few weeks off.
- Label dates come from FDA approval letters; boxed-warning wording from the labels on Drugs@FDA and current labels in openFDA. Only boxed warnings are tracked, not other label sections, and only five drugs so far. Risks are short names for each boxed-warning heading, not the full text.
- Trial dates are PubMed's earliest public date; FDA signal dates are the dates of FDA Drug Safety Communications.
- Lyme disease versions before 2011 are not included yet. Case definitions are dated by CDC's version year; surveillance years follow MMWR weeks, which start within a few days of January 1.
- The metrics use a yearly grid of January 1 dates, so a change and its announcement in the same year look like one event. A finer grid is a one-line change in `metrics.yearly`.
- The ontology and SHACL shapes have not yet been run through an OWL reasoner or a SHACL engine. That is the next step.

## Next
- KGX export for Translator tools, and reasoner/SHACL validation in CI.
- More drugs (openFDA label history) and more conditions (NNDSS case definitions).
- Evidence that evolves beyond labels: meta-analyses entering over time, with an as-of evidence summary.

Issues and corrections are welcome.

## License, credits and contact
- Code: Apache-2.0. Data, ontology and documentation: CC BY 4.0.
- Made by MV2 of Munim, Inc. The work was done with AI agents (Claude) working in his name, and every date was checked against the cited FDA, CDC or PubMed record. Contact: munimversion2@gmail.com.
