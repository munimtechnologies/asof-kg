import contextlib
import datetime as dt
import io
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from asofkg import (GuidelineKG, GuidelineVersion, Instant, Version, VersionChains, allen, audit,  # noqa: E402
                    boxed_warning, check_copy, label_audit, load_case_definitions, load_encounters,
                    load_fills, load_labels, to_turtle, versions_to_turtle)
from asofkg.__main__ import main  # noqa: E402

CRC = "colorectal-cancer-screening"
BREAST = "breast-cancer-screening"
ASPIRIN = "aspirin-primary-prevention-cvd"
LYME = "lyme-disease"
NEURO = ["serious neuropsychiatric events"]
D = dt.date


def version(id, published, supersedes=None, topic="t", recs=None):
    return GuidelineVersion({
        "id": id, "topic": topic, "title": id, "pmid": "0", "journal": "x",
        "published": published, "supersedes": supersedes,
        "recommendations": recs or [{"grade": "A", "age_min": 50, "age_max": 75}],
    })


def chain_version(id, effective, supersedes=None, announced=None, notified=None, subject="s"):
    return Version({"id": id, "subject": subject, "effective": effective, "supersedes": supersedes,
                    "announced": announced, "notified": notified})


class InstantTests(unittest.TestCase):
    def test_precisions(self):
        self.assertEqual(Instant("2016").earliest, D(2016, 1, 1))
        self.assertEqual(Instant("2016").latest, D(2016, 12, 31))
        self.assertEqual(Instant("2024-02").latest, D(2024, 2, 29))
        self.assertEqual(Instant("2016-06-21").earliest, Instant("2016-06-21").latest)
        self.assertEqual(Instant("2016-06").precision, "month")
        self.assertEqual(Instant("2016-06-21").precision, "day")

    def test_known_only_when_certain(self):
        self.assertFalse(Instant("2016").certainly_by("2016-06-30"))
        self.assertTrue(Instant("2016").possibly_by("2016-06-30"))
        self.assertTrue(Instant("2016").certainly_by("2016-12-31"))

    def test_rejects_garbage(self):
        for bad in ("", "16/06/2016", "2016-13", "2016-02-30", "-2016"):
            with self.assertRaises(ValueError):
                Instant(bad)

    def test_allen(self):
        self.assertEqual(allen((D(2016, 6, 21), D(2021, 5, 18)), (D(2021, 5, 18), None)), "meets")
        self.assertEqual(allen((D(2021, 5, 18), None), (D(2016, 6, 21), D(2021, 5, 18))), "met-by")
        self.assertEqual(allen((D(2010, 1, 1), D(2011, 1, 1)), (D(2012, 1, 1), D(2013, 1, 1))), "before")
        self.assertEqual(allen((D(2010, 1, 1), D(2012, 1, 1)), (D(2011, 1, 1), D(2013, 1, 1))), "overlaps")
        self.assertEqual(allen((D(2011, 1, 1), D(2012, 1, 1)), (D(2010, 1, 1), D(2013, 1, 1))), "during")
        self.assertEqual(allen((D(2010, 1, 1), None), (D(2012, 1, 1), None)), "finished-by")
        self.assertEqual(allen((D(2010, 1, 1), D(2011, 1, 1)), (D(2010, 1, 1), D(2011, 1, 1))), "equals")
        self.assertEqual(allen(("2010-01-01", "2011-01-01"), ("2010-01-01", None)), "starts")


class BundledDataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.kg = GuidelineKG.load()

    def grade(self, topic, on, age, sex=None, risk=None):
        rec, _ = self.kg.recommendation(topic, on, age, sex, risk)
        return rec.grade if rec else None

    def test_bundled_data_is_consistent(self):
        self.assertEqual(self.kg.check(), [])

    def test_topics(self):
        self.assertEqual(self.kg.topics(), [ASPIRIN, BREAST, CRC])

    def test_in_force_follows_publication_dates(self):
        self.assertIsNone(self.kg.in_force(CRC, "2008-10-05"))
        self.assertEqual(self.kg.in_force(CRC, "2008-10-06").id, "crc-2008")
        self.assertEqual(self.kg.in_force(CRC, "2010-01-01").id, "crc-2008")
        self.assertEqual(self.kg.in_force(CRC, "2021-05-17").id, "crc-2016")
        self.assertEqual(self.kg.in_force(CRC, "2021-05-18").id, "crc-2021")
        self.assertEqual(self.kg.in_force(BREAST, "2024-06-10").id, "breast-2016")
        self.assertEqual(self.kg.in_force(ASPIRIN, "2026-10-14").id, "aspirin-2022")

    def test_no_hindsight(self):
        # In 2018 nobody could know the 2016 statement would be replaced in 2021.
        self.assertEqual(self.kg.in_force(CRC, "2023-01-01", known_at="2018-01-01").id, "crc-2016")
        self.assertEqual(self.kg.interval("crc-2016", "2018-01-01"), (D(2016, 6, 21), None))
        self.assertEqual(self.kg.interval("crc-2016", "2022-01-01"), (D(2016, 6, 21), D(2021, 5, 18)))
        self.assertIsNone(self.kg.interval("crc-2021", "2020-01-01"))

    def test_no_answer_uses_a_later_source(self):
        day = D(2008, 1, 1)
        while day < D(2027, 1, 1):
            for topic in self.kg.topics():
                for on in (day, day + dt.timedelta(days=2000)):
                    v = self.kg.in_force(topic, on, known_at=day)
                    if v is not None:
                        self.assertLessEqual(v.published.latest, day)
            day += dt.timedelta(days=37)

    def test_intervals_meet(self):
        for v in self.kg.versions:
            if v.supersedes:
                old = self.kg.interval(v.supersedes, "2026-10-14")
                new = self.kg.interval(v.id, "2026-10-14")
                self.assertEqual(allen(old, new), "meets")

    def test_colorectal_ages(self):
        self.assertIsNone(self.grade(CRC, "2022-01-01", 44))
        self.assertEqual(self.grade(CRC, "2022-01-01", 45), "B")
        self.assertEqual(self.grade(CRC, "2022-01-01", 75), "A")
        self.assertEqual(self.grade(CRC, "2022-01-01", 76), "C")
        self.assertIsNone(self.grade(CRC, "2022-01-01", 86))
        self.assertEqual(self.grade(CRC, "2010-01-01", 86), "D")
        self.assertIsNone(self.grade(CRC, "2019-01-01", 46))

    def test_breast_needs_sex(self):
        self.assertEqual(self.grade(BREAST, "2025-01-01", 42, "female"), "B")
        self.assertEqual(self.grade(BREAST, "2023-01-01", 42, "female"), "C")
        self.assertIsNone(self.grade(BREAST, "2025-01-01", 42, "male"))
        self.assertIsNone(self.grade(BREAST, "2025-01-01", 42))

    def test_aspirin_needs_risk(self):
        self.assertEqual(self.grade(ASPIRIN, "2018-01-01", 55, risk=0.12), "B")
        self.assertIsNone(self.grade(ASPIRIN, "2018-01-01", 55, risk=0.05))
        self.assertEqual(self.grade(ASPIRIN, "2023-01-01", 55, risk=0.12), "C")
        self.assertEqual(self.grade(ASPIRIN, "2023-01-01", 65), "D")
        self.assertEqual(self.grade(ASPIRIN, "2018-01-01", 45), "I")

    def test_population_labels(self):
        recs = self.kg.by_id["aspirin-2016"].recommendations
        self.assertEqual([r.population() for r in recs],
                         ["under 50", "50-59, 10-year CVD risk >= 10%", "60-69, 10-year CVD risk >= 10%", "70+"])
        self.assertEqual(self.kg.by_id["breast-2024"].recommendations[0].population(), "female, 40-74")

    def test_audit_against_static(self):
        rows = {r["id"]: r for r in audit(self.kg, load_encounters(), "2026-10-13")}
        self.assertEqual(rows["E1"]["temporal"], {"verdict": "no recommendation", "grade": None, "version": "crc-2016"})
        self.assertEqual(rows["E1"]["static"], {"verdict": "gap", "grade": "B", "version": "crc-2021"})
        self.assertEqual(rows["E3"]["temporal"]["verdict"], "ok")
        self.assertEqual(rows["E3"]["static"]["verdict"], "gap")
        self.assertEqual(rows["E5"]["temporal"]["verdict"], "gap")
        self.assertEqual(rows["E5"]["static"]["verdict"], "ok")
        self.assertEqual(rows["E6"]["temporal"]["verdict"], "against")
        self.assertEqual(rows["E7"]["temporal"]["verdict"], "unknown")
        self.assertEqual(rows["E8"]["temporal"]["version"], "crc-2016")
        self.assertEqual(sorted(k for k, r in rows.items() if not r["agree"]), ["E1", "E3", "E5", "E7", "E8"])


class CheckTests(unittest.TestCase):
    def test_flags_dangling_and_out_of_order(self):
        kg = GuidelineKG([version("a", "2010-01-01"),
                          version("b", "2009-01-01", supersedes="a"),
                          version("c", "2011-01-01", supersedes="zz")])
        problems = "\n".join(kg.check())
        self.assertIn("c supersedes unknown zz", problems)
        self.assertIn("b is not published after a", problems)

    def test_coarse_dates_must_not_overlap(self):
        kg = GuidelineKG([version("a", "2010"), version("b", "2010-06-01", supersedes="a")])
        self.assertIn("b is not published after a", "\n".join(kg.check()))

    def test_flags_cycles(self):
        kg = GuidelineKG([version("a", "2010-01-01", supersedes="b"),
                          version("b", "2011-01-01", supersedes="a")])
        self.assertIn("cycle", "\n".join(kg.check()))

    def test_flags_branches(self):
        kg = GuidelineKG([version("a", "2010-01-01"),
                          version("b", "2011-01-01", supersedes="a"),
                          version("c", "2012-01-01", supersedes="a")])
        self.assertIn("branches", "\n".join(kg.check()))

    def test_flags_overlapping_recommendations(self):
        recs = [{"grade": "A", "age_min": 50, "age_max": 75}, {"grade": "C", "age_min": 70, "age_max": 85}]
        kg = GuidelineKG([version("a", "2010-01-01", recs=recs)])
        self.assertIn("overlapping", "\n".join(kg.check()))

    def test_coarse_publication_is_known_only_after_it_must_have_happened(self):
        kg = GuidelineKG([version("a", "2010")])
        self.assertIsNone(kg.in_force("t", "2010-06-01"))
        self.assertEqual(kg.in_force("t", "2010-12-31").id, "a")

    def test_version_chain_problems(self):
        chains = VersionChains([chain_version("a", "2010-01-01"),
                                chain_version("b", "2009-01-01", supersedes="a"),
                                chain_version("c", "2011-01-01", supersedes="zz"),
                                chain_version("d", "2012-01-01", announced="2011-01-01", notified="2011-06-01")])
        problems = "\n".join(chains.check())
        self.assertIn("b does not take effect after a", problems)
        self.assertIn("c supersedes unknown zz", problems)
        self.assertIn("d was notified after it was announced", problems)

    def test_version_chain_branches(self):
        chains = VersionChains([chain_version("a", "2010-01-01"),
                                chain_version("b", "2011-01-01", supersedes="a"),
                                chain_version("c", "2012-01-01", supersedes="a")])
        self.assertIn("branches", "\n".join(chains.check()))


class LabelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.labels = load_labels()

    def test_label_data_is_consistent(self):
        self.assertEqual(self.labels.check(), [])
        self.assertEqual(self.labels.subjects(), ["levofloxacin", "montelukast", "varenicline"])

    def test_boxed_warning_history(self):
        box = lambda drug, on: boxed_warning(self.labels, drug, on)  # noqa: E731
        self.assertEqual(box("levofloxacin", "2008-10-02"), [])
        self.assertEqual(box("levofloxacin", "2008-10-03"), ["tendinitis and tendon rupture"])
        self.assertEqual(box("levofloxacin", "2011-02-25"),
                         ["tendinitis and tendon rupture", "exacerbation of myasthenia gravis"])
        self.assertEqual(box("varenicline", "2009-06-30"), [])
        self.assertEqual(box("varenicline", "2009-07-01"), NEURO)
        self.assertEqual(box("varenicline", "2016-12-16"), [])
        self.assertEqual(box("montelukast", "2020-04-28"), [])
        self.assertEqual(box("montelukast", "2020-04-29"), NEURO)
        self.assertIsNone(box("montelukast", "1990-01-01"))

    def test_announced_before_it_takes_effect(self):
        self.assertEqual(self.labels.pending("montelukast", "2020-03-03"), [])
        self.assertEqual([v.id for v in self.labels.pending("montelukast", "2020-03-04")], ["montelukast-2020"])
        self.assertEqual(self.labels.pending("montelukast", "2020-04-29"), [])
        # Once the change is announced, the end of the old label is known before it happens.
        self.assertEqual(self.labels.interval("montelukast-1998", "2020-03-01"), (D(1998, 2, 20), None))
        self.assertEqual(self.labels.interval("montelukast-1998", "2020-03-10"), (D(1998, 2, 20), D(2020, 4, 29)))
        self.assertIsNone(self.labels.interval("montelukast-2020", "2020-03-01"))

    def test_sponsor_knows_first(self):
        self.assertEqual(self.labels.pending("varenicline", "2009-03-01"), [])
        self.assertEqual([v.id for v in self.labels.pending("varenicline", "2009-03-01", view="sponsor")],
                         ["varenicline-2009"])
        self.assertEqual(self.labels.pending("levofloxacin", "2010-12-01"), [])
        self.assertEqual([v.id for v in self.labels.pending("levofloxacin", "2010-12-01", view="sponsor")],
                         ["levofloxacin-2011"])
        with self.assertRaises(ValueError):
            self.labels.pending("varenicline", "2009-03-01", view="press")

    def test_no_label_answer_uses_a_later_announcement(self):
        day = D(1996, 1, 1)
        while day < D(2027, 1, 1):
            for drug in self.labels.subjects():
                for on in (day, day + dt.timedelta(days=2000)):
                    v = self.labels.in_force(drug, on, known_at=day)
                    if v is not None:
                        self.assertLessEqual(v.announced.latest, day)
                for v in self.labels.pending(drug, day):
                    self.assertLessEqual(v.announced.latest, day)
            day += dt.timedelta(days=37)

    def test_label_intervals_meet(self):
        for v in self.labels.versions:
            if v.supersedes:
                old = self.labels.interval(v.supersedes, "2026-10-14")
                new = self.labels.interval(v.id, "2026-10-14")
                self.assertEqual(allen(old, new), "meets")

    def test_label_audit_against_static(self):
        rows = {r["id"]: r for r in label_audit(self.labels, load_fills(), "2026-10-13")}
        self.assertTrue(rows["F1"]["agree"])
        self.assertEqual(rows["F1"]["then_version"], "varenicline-2006")
        self.assertEqual(rows["F2"]["then"], NEURO)
        self.assertEqual(rows["F2"]["static"], [])
        self.assertEqual(rows["F2"]["static_version"], "varenicline-2016")
        self.assertEqual(rows["F3"]["then_version"], "varenicline-2009")
        self.assertEqual(rows["F3"]["announced"], [])
        self.assertEqual(rows["F5"]["then"], [])
        self.assertEqual(rows["F5"]["announced"], ["montelukast-2020"])
        self.assertEqual(rows["F5"]["static"], NEURO)
        self.assertEqual(rows["F8"]["then_version"], "levofloxacin-2011")
        self.assertEqual(rows["F8"]["announced"], ["levofloxacin-2016"])
        self.assertEqual(sorted(k for k, r in rows.items() if not r["agree"]),
                         ["F2", "F3", "F4", "F5", "F6", "F7", "F8"])

    def test_stale_copy(self):
        # A label copy dated 2020-02-01 that still shows the boxed warning removed in 2016.
        self.assertEqual(check_copy(self.labels, "varenicline", "2020-02-01", True),
                         {"expected": "varenicline-2016", "consistent": False, "older": ["varenicline-2009"]})
        self.assertEqual(check_copy(self.labels, "montelukast", "2021-01-01", True),
                         {"expected": "montelukast-2020", "consistent": True, "older": []})


class CaseDefinitionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cd = load_case_definitions()

    def test_case_definition_data_is_consistent(self):
        self.assertEqual(self.cd.check(), [])

    def test_known_before_in_force(self):
        self.assertIsNone(self.cd.in_force(LYME, "2010-06-01"))
        self.assertEqual(self.cd.in_force(LYME, "2021-07-01").id, "lyme-2017")
        self.assertEqual(self.cd.in_force(LYME, "2022-03-01").id, "lyme-2022")
        self.assertEqual(self.cd.pending(LYME, "2021-06-29"), [])
        self.assertEqual([v.id for v in self.cd.pending(LYME, "2021-07-01")], ["lyme-2022"])
        self.assertEqual(self.cd.interval("lyme-2017", "2021-06-29"), (D(2017, 1, 1), None))
        self.assertEqual(self.cd.interval("lyme-2017", "2021-07-01"), (D(2017, 1, 1), D(2022, 1, 1)))

    def test_year_only_adoption_counts_from_year_end(self):
        self.assertEqual(self.cd.pending(LYME, "2016-12-30"), [])
        self.assertEqual([v.id for v in self.cd.pending(LYME, "2016-12-31")], ["lyme-2017"])


class TurtleTests(unittest.TestCase):
    def test_snapshot_hides_later_versions(self):
        kg = GuidelineKG.load()
        ttl_2018 = to_turtle(kg, "2018-01-01")
        self.assertIn("akgd:crc-2016 a akg:GuidelineVersion", ttl_2018)
        self.assertNotIn("crc-2021", ttl_2018)
        block = ttl_2018.split("akgd:crc-2016-interval a")[1].split("\n\n")[0]
        self.assertNotIn("time:hasEnd", block)

    def test_full_graph(self):
        full = to_turtle(GuidelineKG.load())
        self.assertIn('time:hasEnd [ a time:Instant ; time:inXSDDate "2021-05-18"^^xsd:date ]', full)
        self.assertIn("akg:supersedes akgd:crc-2016", full)
        self.assertIn("akg:hasGrade akg:GradeB", full)
        self.assertIn("akg:sex obo:PATO_0000383", full)
        self.assertIn('akg:minTenYearCvdRisk "0.1"^^xsd:decimal', full)
        self.assertIn("MESH:D015179 a biolink:Disease", full)
        self.assertEqual(full.count(" a akg:GuidelineVersion ;"), 8)

    def test_label_snapshots(self):
        labels = load_labels()
        ttl = versions_to_turtle(labels, "2020-04-01")
        self.assertIn("akgd:montelukast-2020 a akg:LabelVersion", ttl)
        self.assertIn('time:hasEnd [ a time:Instant ; time:inXSDDate "2020-04-29"^^xsd:date ]', ttl)
        self.assertIn("akgd:levofloxacin-2016 a akg:LabelVersion", ttl)
        self.assertNotIn("akg:notifiedOn", ttl)
        public = versions_to_turtle(labels, "2009-03-01")
        self.assertNotIn("varenicline-2009", public)
        sponsor = versions_to_turtle(labels, "2009-03-01", view="sponsor")
        self.assertIn("# Snapshot (sponsor view): only what was known by 2009-03-01.", sponsor)
        self.assertIn("akgd:varenicline-2009 a akg:LabelVersion", sponsor)
        self.assertIn('akg:notifiedOn "2009-02-19"^^xsd:date', sponsor)

    def test_full_label_graph(self):
        full = versions_to_turtle(load_labels())
        self.assertEqual(full.count(" a akg:LabelVersion ;"), 9)
        self.assertIn("a akg:LabelVersionWithoutBoxedWarning ;", full)
        self.assertIn('akg:boxedWarningRisk "exacerbation of myasthenia gravis"@en', full)
        self.assertIn("RXNORM:591622 a biolink:Drug", full)

    def test_case_definition_graph(self):
        full = versions_to_turtle(load_case_definitions())
        self.assertEqual(full.count(" a akg:CaseDefinitionVersion ;"), 3)
        self.assertIn('akg:positionStatement "21-ID-05"', full)
        self.assertIn("akg:aboutCondition MESH:D008193", full)

    def test_ontology_file_present(self):
        with open(os.path.join(HERE, "ontology", "asofkg.ttl"), encoding="utf-8") as f:
            text = f.read()
        self.assertIn("owl:Ontology", text)
        for term in ("akg:supersedes", "akg:inForceDuring", "akg:validDuring", "akg:Recommendation",
                     "akg:Version", "akg:LabelVersion", "akg:CaseDefinitionVersion",
                     "akg:effectiveFrom", "akg:announcedOn", "akg:notifiedOn", "akg:boxedWarningRisk"):
            self.assertIn(term + " a owl:", text)

    def test_shapes_file_present(self):
        with open(os.path.join(HERE, "shapes", "asofkg-shapes.ttl"), encoding="utf-8") as f:
            text = f.read()
        for shape in ("akg:GuidelineVersionShape", "akg:EffectiveVersionShape", "akg:RecommendationShape"):
            self.assertIn(shape + " a sh:NodeShape", text)


class CliTests(unittest.TestCase):
    def run_main(self, *argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = main(list(argv))
        return code, out.getvalue()

    def test_check(self):
        code, out = self.run_main("check")
        self.assertEqual(code, 0)
        self.assertIn("0 problem(s)", out)

    def test_demo(self):
        code, out = self.run_main("demo", "--known-at", "2026-10-13")
        self.assertEqual(code, 0)
        self.assertIn("5 of 8 verdicts change when time is ignored.", out)

    def test_labels(self):
        code, out = self.run_main("labels", "--known-at", "2026-10-13")
        self.assertEqual(code, 0)
        self.assertIn("7 of 8 boxed-warning answers change when time is ignored.", out)
        self.assertIn("announced, not yet on the label: montelukast-2020", out)

    def test_ttl(self):
        code, out = self.run_main("ttl", "--known-at", "2018-01-01")
        self.assertEqual(code, 0)
        self.assertIn("# Snapshot: only what was published by 2018-01-01.", out)
        self.assertIn("akgd:lyme-2017 a akg:CaseDefinitionVersion", out)
        self.assertNotIn("lyme-2022", out)

    def test_ttl_sponsor_view(self):
        code, out = self.run_main("ttl", "--known-at", "2009-03-01", "--view", "sponsor")
        self.assertEqual(code, 0)
        self.assertIn("akg:notifiedOn", out)


if __name__ == "__main__":
    unittest.main()
