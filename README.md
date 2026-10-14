# asof-kg: clinical guidelines as they stood on any date

Most medical knowledge graphs store facts with no time attached. They cannot tell "what is recommended now" from "what was recommended when the patient was seen", and they quietly use knowledge published later. asof-kg is a small, open prototype that keeps both times:

- **Valid time:** when a guideline version was in force.
- **Knowledge time:** when a fact could first be known. A version is known from its publication date. The *end* of its time in force is known only once a successor has been published.

Every query takes a `known_at` date and never uses anything published after it. Version 0.1.0, 2026-10-14.

> **Not medical advice.** This is research software and research data. It does not tell anyone what care to get. Ask a clinician.

## What's in it
| Path | What it is |
|---|---|
| `asofkg/` | Python 3.7+ package, standard library only: as-of queries, consistency checks, Turtle export, CLI |
| `asofkg/data/uspstf.json` | 8 USPSTF recommendation statements on 3 topics (2008-2024), each with its PMID |
| `asofkg/data/synthetic_encounters.json` | 8 made-up encounters for the demo audit (no real people) |
| `ontology/asofkg.ttl` | OWL 2 ontology built on OWL-Time and PROV-O, aligned to Biolink, MeSH and PATO |
| `shapes/asofkg-shapes.ttl` | SHACL rules for temporal consistency that OWL cannot express |
| `queries/*.rq` | SPARQL competency queries (as-of version, recommendation for a person) |
| `test_asofkg.py` | unittest suite |

## Run it
```
python -m asofkg demo --known-at 2026-10-13   # care-gap audit: in force then vs newest only
python -m asofkg check                        # consistency report
python -m asofkg ttl --known-at 2018-01-01    # the graph as it could be known on that date
python -m unittest test_asofkg                # tests
```

## What the demo shows
A care-gap audit asks whether a recommended service was missed at a past visit. Done with time, it applies the version in force on the visit date. Done without time, it applies the newest version to every visit. The tests pin these verdicts for the synthetic encounters (all "not done" except E6):

| Encounter | Visit | In force then | Newest version only |
|---|---|---|---|
| E1: colorectal, age 46 | 2019-03-01 | no recommendation (2016 statement starts at 50) | gap (grade B, 2021) |
| E3: breast, woman 42 | 2023-05-01 | ok (grade C, 2016) | gap (grade B, 2024) |
| E5: aspirin, age 55, risk 12% | 2018-06-01 | gap (grade B, 2016) | ok (grade C, 2022) |
| E7: colorectal, age 55 | 2007-06-01 | unknown (no version in this graph yet) | gap (grade A, 2021) |
| E8: colorectal, age 46 | 2021-05-17 | no recommendation (one day before the 2021 statement) | gap (grade B, 2021) |

So 5 of the 8 verdicts change when time is ignored, in both directions: false gaps (E1, E3, E8) and a missed gap (E5).

## How time is handled
- **No hindsight:** `in_force(topic, on, known_at)` sees only versions published by `known_at`. `interval(version, known_at)` leaves the end open until a successor is published. In 2018 the 2016 colorectal statement has no known end; from 2021-05-18 on, it ends that day. A test sweeps 2008-2026 to check that no answer uses a later source.
- **Coarse dates:** a date given only as a year or month counts as known only once its latest possible day has passed (`Instant`).
- **Interval algebra:** `allen()` gives all 13 Allen relations. Consecutive versions must *meet*, and the tests check that.
- **Consistency:** `check()` and the SHACL shapes flag versions published before the one they replace, supersession cycles and branches, cross-topic supersession, overlapping age bands, and interval ends asserted before any successor exists.

## Ontology notes
- `akg:GuidelineVersion` ⊑ `biolink:Publication`, `prov:Entity`. `akg:Recommendation` ⊑ `biolink:Association`. Conditions are MeSH terms typed `biolink:Disease`, and sex uses PATO.
- `akg:supersedes` is asymmetric and irreflexive, and is a sub-property of `prov:wasRevisionOf` and of the transitive `akg:laterVersionOf`.
- `akg:validDuring` is inferred by a property chain (`partOfGuideline` ∘ `inForceDuring`). `RoutineRecommendation` and `RecommendationAgainst` are defined classes that a reasoner fills in from the grade.
- Biolink's `temporal_interval_qualifier` is string-valued, so it cannot point at an OWL-Time interval. `akg:inForceDuring` carries the interval and maps to it with `skos:relatedMatch`.
- Dates use `xsd:date`, as OWL-Time's `time:inXSDDate` does. Some OWL 2 DL reasoners need their "ignore unsupported datatypes" option for it.

## Data sources and limits
- Grades, age bands and dates come from PubMed records (NCBI E-utilities, checked 2026-10-14). The `published` date is PubMed's earliest public date (electronic publication if present, else issue date). The journal sometimes posted a statement online earlier, so a boundary may be a few weeks off.
- Only 3 topics and 8 versions so far. Conditions attached to a grade (bleeding risk, life expectancy, and so on) are kept as notes, not modelled.
- The ontology and SHACL shapes have not yet been run through an OWL reasoner or SHACL engine. That is the next step.

## Next
- Pharmacovigilance: drug-label safety changes (boxed warnings added and removed) as versions with knowledge time.
- Evolving evidence: trial results and meta-analyses entering over time, with an as-of evidence summary.
- KGX export for Translator tools, and reasoner/SHACL validation in CI.

Issues and corrections are welcome.

## License, credits and contact
- Code: MIT. Data, ontology and documentation: CC BY 4.0.
- Made by MV2 of Munim, Inc. The work was done with AI agents (Claude) working in his name, and every figure was checked against the cited PubMed record. Contact: munimversion2@gmail.com.
