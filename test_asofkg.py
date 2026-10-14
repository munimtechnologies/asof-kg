import collections
import contextlib
import datetime as dt
import io
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from asofkg import (GuidelineKG, GuidelineVersion, Instant, Version, VersionChains, allen, audit,  # noqa: E402
                    boxed_warning, check_copy, evidence_lag, fact_spans, guideline_points, label_audit,
                    load_case_definitions, load_encounters, load_fills, load_labels, summarize, to_kgx,
                    to_turtle, version_points, versions_to_turtle, write_kgx, yearly)
from asofkg.__main__ import main  # noqa: E402
from asofkg.kgx import EDGE_COLUMNS, NODE_COLUMNS  # noqa: E402

CRC = "colorectal-cancer-screening"
BREAST = "breast-cancer-screening"
ASPIRIN = "aspirin-primary-prevention-cvd"
LYME = "lyme-disease"
NEURO = ["serious neuropsychiatric events"]
AKG = "@prefix akg: <https://github.com/munimtechnologies/asof-kg/ontology#> ."
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

    def test_flags_terms_no_version_uses(self):
        chains = VersionChains([chain_version("a", "2010-01-01")], terms={"x": []})
        self.assertEqual(chains.check(), ["terms given for 'x', which no version uses"])


class LabelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.labels = load_labels()

    def test_label_data_is_consistent(self):
        self.assertEqual(self.labels.check(), [])
        self.assertEqual(self.labels.subjects(),
                         ["febuxostat", "levofloxacin", "montelukast", "tofacitinib", "varenicline"])
        self.assertEqual(len(self.labels.terms), 6)

    def test_boxed_warning_history(self):
        box = lambda drug, on, known_at=None: boxed_warning(self.labels, drug, on, known_at)  # noqa: E731
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
        self.assertEqual(box("febuxostat", "2019-02-20"), [])
        self.assertEqual(box("febuxostat", "2019-02-21"), ["cardiovascular death"])
        self.assertEqual(box("tofacitinib", "2012-11-06"), ["serious infections", "malignancy"])
        self.assertEqual(box("tofacitinib", "2021-12-02"),
                         ["serious infections", "mortality", "malignancy",
                          "major adverse cardiovascular events", "thrombosis"])

    def test_announced_after_it_took_effect(self):
        # The 2019 tofacitinib label was approved on July 25 and announced on July 26.
        self.assertEqual(boxed_warning(self.labels, "tofacitinib", "2019-07-25"),
                         ["serious infections", "malignancy"])
        self.assertEqual(boxed_warning(self.labels, "tofacitinib", "2019-07-25", known_at="2019-07-26"),
                         ["serious infections", "mortality", "malignancy", "thrombosis"])
        self.assertEqual(self.labels.interval("tofacitinib-2012", "2019-07-25"), (D(2012, 11, 6), None))
        self.assertEqual(self.labels.interval("tofacitinib-2012", "2019-07-26"),
                         (D(2012, 11, 6), D(2019, 7, 25)))

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
        self.assertEqual(self.labels.pending("tofacitinib", "2021-08-25"), [])
        self.assertEqual([v.id for v in self.labels.pending("tofacitinib", "2021-08-25", view="sponsor")],
                         ["tofacitinib-2021"])
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
        self.assertEqual(rows["F9"]["then_version"], "tofacitinib-2012")
        self.assertEqual(rows["F9"]["announced"], [])
        self.assertEqual(rows["F10"]["then"], [])
        self.assertEqual(rows["F10"]["static"], ["cardiovascular death"])
        self.assertEqual(rows["F11"]["then_version"], "tofacitinib-2019")
        self.assertEqual(rows["F11"]["announced"], ["tofacitinib-2021"])
        self.assertEqual(sorted(k for k, r in rows.items() if not r["agree"]),
                         ["F10", "F11", "F2", "F3", "F4", "F5", "F6", "F7", "F8", "F9"])

    def test_stale_copy(self):
        # A label copy dated 2020-02-01 that still shows the boxed warning removed in 2016.
        self.assertEqual(check_copy(self.labels, "varenicline", "2020-02-01", True),
                         {"expected": "varenicline-2016", "consistent": False, "older": ["varenicline-2009"]})
        self.assertEqual(check_copy(self.labels, "montelukast", "2021-01-01", True),
                         {"expected": "montelukast-2020", "consistent": True, "older": []})


class RiskSpanTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.labels = load_labels()

    def spans(self, known_at=None, view="public"):
        return {(s["subject"], s["value"]): s for s in fact_spans(self.labels, "boxed_warning", known_at, view)}

    def test_all_spans(self):
        spans = self.spans()
        self.assertEqual(len(spans), 13)
        self.assertEqual([k for k, s in spans.items() if s["end"] is not None], [("varenicline", NEURO[0])])
        levo = [s["value"] for s in fact_spans(self.labels, "boxed_warning") if s["subject"] == "levofloxacin"]
        self.assertEqual(levo, ["tendinitis and tendon rupture", "exacerbation of myasthenia gravis",
                                "disabling and potentially irreversible serious adverse reactions",
                                "peripheral neuropathy", "central nervous system effects"])

    def test_removed_risk(self):
        s = self.spans()[("varenicline", NEURO[0])]
        self.assertEqual((s["start"], s["end"]), (D(2009, 7, 1), D(2016, 12, 16)))
        self.assertEqual((s["started_by"], s["ended_by"]), ("varenicline-2009", "varenicline-2016"))
        self.assertEqual((s["start_known_from"], s["end_known_from"]), (D(2009, 7, 1), D(2016, 12, 16)))
        self.assertEqual(self.spans(view="sponsor")[("varenicline", NEURO[0])]["start_known_from"], D(2009, 2, 19))
        # Before the removal was known, the span is open.
        self.assertIsNone(self.spans("2016-06-01")[("varenicline", NEURO[0])]["end"])

    def test_known_before_and_after_it_took_effect(self):
        mont = self.spans()[("montelukast", NEURO[0])]
        self.assertEqual((mont["start"], mont["start_known_from"]), (D(2020, 4, 29), D(2020, 3, 4)))
        self.assertNotIn(("montelukast", NEURO[0]), self.spans("2020-03-01"))
        self.assertEqual(self.spans("2020-03-10")[("montelukast", NEURO[0])]["start"], D(2020, 4, 29))
        clot = self.spans()[("tofacitinib", "thrombosis")]
        self.assertEqual((clot["start"], clot["start_known_from"]), (D(2019, 7, 25), D(2019, 7, 26)))

    def test_who_knew_first(self):
        for view, before, after in (("public", 6, 2), ("sponsor", 10, 0)):
            spans = fact_spans(self.labels, "boxed_warning", None, view)
            self.assertEqual(sum(1 for s in spans if s["start_known_from"] < s["start"]), before)
            self.assertEqual(sum(1 for s in spans if s["start_known_from"] > s["start"]), after)


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


class MetricsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.kg = GuidelineKG.load()
        cls.labels = load_labels()
        cls.cd = load_case_definitions()
        cls.years = yearly(2000, 2026)

    def counts(self, summary):
        return summary["queries"], summary["changed"], summary["leaked"], summary["hindsight"]

    def test_yearly(self):
        self.assertEqual(len(self.years), 27)
        self.assertEqual((self.years[0], self.years[-1]), (D(2000, 1, 1), D(2026, 1, 1)))

    def test_guideline_metrics(self):
        self.assertEqual(self.counts(summarize(guideline_points(self.kg, self.years))), (45, 34, 34, 0))

    def test_label_metrics(self):
        rows = version_points(self.labels, self.years, fact="boxed_warning")
        self.assertEqual(self.counts(summarize(rows)), (105, 67, 67, 0))
        self.assertEqual(self.counts(summarize(rows, by="value")), (105, 64, 67, 0))
        vare = [r for r in rows if r["subject"] == "varenicline"]
        self.assertEqual(self.counts(summarize(vare)), (20, 10, 10, 0))
        self.assertEqual(summarize(vare, by="value")["changed"], 7)
        # 2007-2009: "no boxed warning" from the newest label is right, but only through the 2016 removal.
        lucky = [r["day"].year for r in vare if not r["static_known"] and r["then_value"] == r["static_value"]]
        self.assertEqual(lucky, [2007, 2008, 2009])

    def test_case_definition_metrics(self):
        self.assertEqual(self.counts(summarize(version_points(self.cd, self.years))), (16, 11, 11, 0))

    def test_skips_days_before_the_first_version(self):
        rows = version_points(self.labels, self.years)
        self.assertEqual(min(r["day"] for r in rows if r["subject"] == "tofacitinib"), D(2013, 1, 1))
        self.assertEqual(min(r["day"] for r in guideline_points(self.kg, self.years) if r["subject"] == ASPIRIN),
                         D(2017, 1, 1))

    def test_no_hindsight_on_a_fine_grid(self):
        days = [D(1996, 1, 1) + dt.timedelta(days=n) for n in range(0, 11400, 11)]
        for view in ("public", "sponsor"):
            self.assertEqual(summarize(version_points(self.labels, days, view))["hindsight"], 0)
            self.assertEqual(summarize(version_points(self.cd, days, view))["hindsight"], 0)
        self.assertEqual(summarize(guideline_points(self.kg, days))["hindsight"], 0)

    def test_rates(self):
        s = summarize(version_points(self.cd, self.years))
        self.assertAlmostEqual(s["changed_rate"], 11 / 16)
        self.assertEqual(summarize([])["changed_rate"], 0.0)
        with self.assertRaises(ValueError):
            summarize([], by="grade")

    def test_evidence_lag(self):
        rows = {r["id"]: r for r in evidence_lag(self.labels)}
        self.assertEqual(sorted(rows), ["febuxostat-2019", "tofacitinib-2019", "tofacitinib-2021", "varenicline-2016"])
        self.assertEqual(rows["varenicline-2016"]["evidence_lag_days"], 238)
        self.assertIsNone(rows["varenicline-2016"]["signal_lag_days"])
        self.assertEqual(rows["febuxostat-2019"]["evidence_pmid"], "29527974")
        self.assertEqual(rows["febuxostat-2019"]["evidence_lag_days"], 346)
        self.assertEqual(rows["febuxostat-2019"]["signal_lag_days"], 463)
        self.assertIsNone(rows["tofacitinib-2019"]["evidence_lag_days"])
        self.assertEqual(rows["tofacitinib-2019"]["signal_lag_days"], 150)
        # The label changed before the trial report appeared in a journal.
        self.assertEqual(rows["tofacitinib-2021"]["evidence_lag_days"], -56)
        self.assertEqual(rows["tofacitinib-2021"]["signal_lag_days"], 301)


class KgxTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.kg = GuidelineKG.load()
        cls.labels = load_labels()
        cls.cd = load_case_definitions()

    def graph(self, known_at=None, view="public"):
        nodes, edges = to_kgx(self.kg, self.labels, self.cd, known_at, view)
        return {n["id"]: n for n in nodes}, {e["id"]: e for e in edges}, nodes, edges

    def test_full_graph(self):
        nodes, edges, node_list, edge_list = self.graph()
        self.assertEqual((len(node_list), len(edge_list)), (46, 56))
        self.assertEqual((len(nodes), len(edges)), (46, 56))  # ids are unique
        self.assertEqual(collections.Counter(n["category"] for n in node_list),
                         {"biolink:Publication": 11, "biolink:InformationContentEntity": 17, "biolink:Drug": 6,
                          "biolink:Disease": 4, "biolink:Procedure": 1, "biolink:DiseaseOrPhenotypicFeature": 7})
        self.assertEqual(collections.Counter(e["predicate"] for e in edge_list),
                         {"biolink:mentions": 30, "biolink:related_to_at_instance_level": 19,
                          "biolink:has_adverse_event": 7})
        for e in edge_list:
            self.assertIn(e["subject"], nodes)
            self.assertIn(e["object"], nodes)
            self.assertEqual((e["knowledge_level"], e["agent_type"]), ("knowledge_assertion", "manual_agent"))

    def test_versions_and_links(self):
        nodes, edges, _, _ = self.graph()
        self.assertEqual(nodes["akgd:crc-2016"]["xref"], "PMID:27304597")
        self.assertEqual((nodes["akgd:crc-2016"]["valid_from"], nodes["akgd:crc-2016"]["valid_to"]),
                         ("2016-06-21", "2021-05-18"))
        vare = nodes["akgd:varenicline-2009"]
        self.assertEqual((vare["category"], vare["valid_from"], vare["valid_to"], vare["known_from"]),
                         ("biolink:InformationContentEntity", "2009-07-01", "2016-12-16", "2009-07-01"))
        self.assertEqual(edges["akgd:crc-2021-revises-crc-2016"]["original_predicate"], "prov:wasRevisionOf")
        trial = edges["akgd:febuxostat-2019-evidence-29527974"]
        self.assertEqual((trial["object"], trial["original_predicate"]), ("PMID:29527974", "prov:wasInfluencedBy"))
        self.assertEqual(edges["akgd:lyme-2022-mentions-D008193"]["object"], "MESH:D008193")
        self.assertEqual(nodes["MESH:D008327"]["category"], "biolink:Procedure")

    def test_adverse_event_edges(self):
        _, edges, _, _ = self.graph()
        # 4 levofloxacin (tendon risk maps to two MeSH terms) and 3 tofacitinib; the other risks are unmapped.
        self.assertEqual({k for k, e in edges.items() if e["predicate"] == "biolink:has_adverse_event"},
                         {"akgd:levofloxacin-ae-D052256-2008-10-03", "akgd:levofloxacin-ae-D013708-2008-10-03",
                          "akgd:levofloxacin-ae-D009157-2011-02-25", "akgd:levofloxacin-ae-D010523-2016-07-26",
                          "akgd:tofacitinib-ae-D007239-2012-11-06", "akgd:tofacitinib-ae-D009369-2012-11-06",
                          "akgd:tofacitinib-ae-D013927-2019-07-25"})
        clot = edges["akgd:tofacitinib-ae-D013927-2019-07-25"]
        self.assertEqual((clot["subject"], clot["predicate"], clot["object"]),
                         ("RXNORM:1357536", "biolink:has_adverse_event", "MESH:D013927"))
        self.assertEqual((clot["valid_from"], clot["valid_to"], clot["known_from"]), ("2019-07-25", "", "2019-07-26"))
        self.assertEqual(clot["description"], "boxed warning: thrombosis")
        self.assertEqual(edges["akgd:levofloxacin-ae-D013708-2008-10-03"]["known_from"], "2008-07-08")
        _, sponsor, _, _ = self.graph(view="sponsor")
        self.assertEqual(sponsor["akgd:tofacitinib-ae-D013927-2019-07-25"]["known_from"], "2019-05-09")

    def test_snapshot(self):
        nodes, edges, node_list, edge_list = self.graph("2018-01-01")
        self.assertEqual((len(node_list), len(edge_list)), (35, 35))
        self.assertNotIn("akgd:crc-2021", nodes)
        self.assertNotIn("MESH:D013927", nodes)
        self.assertNotIn("PMID:29527974", nodes)
        self.assertEqual(nodes["akgd:crc-2016"]["valid_to"], "")
        for e in edge_list:
            self.assertIn(e["subject"], nodes)
            self.assertIn(e["object"], nodes)
        # Announced on 2020-03-04, so by 2020-03-10 the old label's end is known ahead of time.
        nodes, _, _, _ = self.graph("2020-03-10")
        self.assertEqual(nodes["akgd:montelukast-1998"]["valid_to"], "2020-04-29")
        nodes, _, _, _ = self.graph("2009-03-01", view="sponsor")
        self.assertEqual((nodes["akgd:varenicline-2009"]["valid_from"], nodes["akgd:varenicline-2009"]["known_from"]),
                         ("2009-07-01", "2009-02-19"))

    def test_write_tsv(self):
        nodes, edges = to_kgx(self.kg, self.labels, self.cd)
        with tempfile.TemporaryDirectory() as tmp:
            node_path, edge_path = write_kgx(nodes, edges, os.path.join(tmp, "out"))
            with open(node_path, encoding="utf-8") as f:
                node_lines = f.read().splitlines()
            with open(edge_path, encoding="utf-8") as f:
                edge_lines = f.read().splitlines()
        self.assertEqual(node_lines[0], "\t".join(NODE_COLUMNS))
        self.assertEqual(edge_lines[0], "\t".join(EDGE_COLUMNS))
        self.assertEqual((len(node_lines), len(edge_lines)), (47, 57))
        self.assertTrue(all(len(line.split("\t")) == len(NODE_COLUMNS) for line in node_lines))
        self.assertTrue(all(len(line.split("\t")) == len(EDGE_COLUMNS) for line in edge_lines))


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
        self.assertEqual(full.count(" a akg:LabelVersion ;"), 14)
        self.assertIn("a akg:LabelVersionWithoutBoxedWarning ;", full)
        self.assertIn('akg:boxedWarningRisk "exacerbation of myasthenia gravis"@en', full)
        self.assertIn('akg:boxedWarningRisk "major adverse cardiovascular events"@en', full)
        self.assertIn("RXNORM:591622 a biolink:Drug", full)
        self.assertIn("RXNORM:73689 a biolink:Drug", full)
        self.assertIn("RXNORM:1357536 a biolink:Drug", full)
        self.assertIn("prov:wasInfluencedBy pubmed:29527974 ;", full)
        self.assertEqual(full.count("prov:wasInfluencedBy pubmed:"), 3)

    def test_evidence_link_hidden_until_the_change_is_known(self):
        ttl = versions_to_turtle(load_labels(), "2018-06-01")
        self.assertNotIn("pubmed:29527974", ttl)
        self.assertIn("akgd:febuxostat-2009 a akg:LabelVersion", ttl)

    def test_case_definition_graph(self):
        full = versions_to_turtle(load_case_definitions())
        self.assertEqual(full.count(" a akg:CaseDefinitionVersion ;"), 3)
        self.assertIn('akg:positionStatement "21-ID-05"', full)
        self.assertIn("akg:aboutCondition MESH:D008193", full)

    def test_ontology_file_present(self):
        with open(os.path.join(HERE, "ontology", "asofkg.ttl"), encoding="utf-8") as f:
            text = f.read()
        self.assertIn("owl:Ontology", text)
        self.assertIn('owl:versionInfo "0.4.0"', text)
        for term in ("akg:supersedes", "akg:inForceDuring", "akg:validDuring", "akg:Recommendation",
                     "akg:Version", "akg:LabelVersion", "akg:CaseDefinitionVersion",
                     "akg:effectiveFrom", "akg:announcedOn", "akg:notifiedOn", "akg:boxedWarningRisk",
                     "prov:wasInfluencedBy"):
            self.assertIn(term + " a owl:", text)

    def test_shapes_file_present(self):
        with open(os.path.join(HERE, "shapes", "asofkg-shapes.ttl"), encoding="utf-8") as f:
            text = f.read()
        for shape in ("akg:GuidelineVersionShape", "akg:EffectiveVersionShape", "akg:RecommendationShape"):
            self.assertIn(shape + " a sh:NodeShape", text)

    def test_one_namespace_everywhere(self):
        # The ontology, the shapes and the instance data must use the same akg: namespace.
        for path in (("ontology", "asofkg.ttl"), ("shapes", "asofkg-shapes.ttl")):
            with open(os.path.join(HERE, *path), encoding="utf-8") as f:
                text = f.read()
            self.assertIn(AKG, text)
            self.assertNotIn("github.com/munimv2/", text)
        self.assertIn(AKG, to_turtle(GuidelineKG.load()))
        self.assertIn(AKG, versions_to_turtle(load_labels()))


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
        self.assertIn("10 of 11 boxed-warning answers change when time is ignored.", out)
        self.assertIn("announced, not yet on the label: montelukast-2020", out)
        self.assertIn("announced, not yet on the label: tofacitinib-2021", out)

    def test_metrics(self):
        code, out = self.run_main("metrics", "--known-at", "2026-10-14")
        self.assertEqual(code, 0)
        self.assertIn("on January 1 of 2000-2026 (public view)", out)
        self.assertIn("34 (76%)", out)
        self.assertIn("64 (61%)", out)
        self.assertIn("11 (69%)", out)
        self.assertIn("112 (67%)", out)
        self.assertIn("trial report 2018-03-12 (346 days before)", out)
        self.assertIn("trial report 2022-01-27 (56 days after)", out)
        self.assertIn("FDA signal notice 2019-02-25 (150 days before)", out)

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

    def test_kgx(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, out = self.run_main("kgx", "--out", tmp)
            self.assertTrue(os.path.exists(os.path.join(tmp, "nodes.tsv")))
        self.assertEqual(code, 0)
        self.assertIn("46 nodes -> ", out)
        self.assertIn("56 edges -> ", out)


if __name__ == "__main__":
    unittest.main()
