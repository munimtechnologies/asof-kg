import datetime as dt
import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from label_sync import audit, classify, excluded, has_text, label_day, latest_per_set, load_history, risks_in, write  # noqa: E402

NEURO = "serious neuropsychiatric events"
TENDON = "tendinitis and tendon rupture"


def v(id, effective, box):
    return {"id": id, "subject": id.split("-")[0], "effective": effective, "facts": {"boxed_warning": box}}


VARENICLINE = [v("varenicline-2006", "2006-05-10", []),
               v("varenicline-2009", "2009-07-01", [NEURO]),
               v("varenicline-2016", "2016-12-16", [])]
MONTELUKAST = [v("montelukast-1998", "1998-02-20", []),
               v("montelukast-2020", "2020-04-29", [NEURO])]
TOFACITINIB = [v("tofacitinib-2012", "2012-11-06", ["serious infections", "malignancy"]),
               v("tofacitinib-2019", "2019-07-25", ["serious infections", "mortality", "malignancy", "thrombosis"]),
               v("tofacitinib-2021", "2021-12-02", ["serious infections", "mortality", "malignancy",
                                                    "major adverse cardiovascular events", "thrombosis"])]
LEVOFLOXACIN = [v("levofloxacin-1996", "1996-12-20", []), v("levofloxacin-2008", "2008-10-03", [TENDON])]
TEXT = {"indications_and_usage": ["1 INDICATIONS AND USAGE ..."]}


def label(effective_time, box=None, set_id="s1", version="1", routes=("ORAL",), **sections):
    record = {"set_id": set_id, "version": version, "effective_time": effective_time,
              "openfda": {"manufacturer_name": ["Example Labs"], "route": list(routes)}}
    if box is not None:
        record["boxed_warning"] = [box]
    record.update(sections)
    return record


class ClassifyTests(unittest.TestCase):
    def test_removed_warning_still_carried(self):
        r = classify(label("20200201", "WARNING: SERIOUS NEUROPSYCHIATRIC EVENTS ..."), VARENICLINE)
        self.assertEqual((r["status"], r["carried"], r["missing"]), ("stale", [NEURO], []))
        self.assertEqual(r["agrees_with"], ["varenicline-2009"])
        self.assertEqual(r["stale_since"], dt.date(2016, 12, 16))
        self.assertEqual(r["days_after_change"], (dt.date(2020, 2, 1) - dt.date(2016, 12, 16)).days)

    def test_no_warning_when_none_is_required(self):
        r = classify(label("20230101"), VARENICLINE)
        self.assertEqual(r["status"], "current")
        self.assertEqual(r["agrees_with"], ["varenicline-2006", "varenicline-2016"])
        self.assertIsNone(r["stale_since"])

    def test_required_warning_missing(self):
        r = classify(label("20251216", None, warnings_and_cautions=["5.4 Neuropsychiatric Events ..."]), MONTELUKAST)
        self.assertEqual((r["status"], r["missing"]), ("stale", [NEURO]))
        self.assertEqual(r["agrees_with"], ["montelukast-1998"])
        self.assertEqual(r["stale_since"], dt.date(2020, 4, 29))
        self.assertEqual(r["days_after_change"], (dt.date(2025, 12, 16) - dt.date(2020, 4, 29)).days)

    def test_warning_present_but_not_split_out(self):
        r = classify(label("20240816", None, use_in_specific_populations=["... [see Boxed Warning] ..."]),
                     MONTELUKAST)
        self.assertEqual((r["status"], r["agrees_with"], r["stale_since"]), ("unparsed", [], None))
        # The box's own heading, filed under another section.
        heading = ["WARNING: SERIOUS NEUROPSYCHIATRIC EVENTS Serious neuropsychiatric (NP) events have been reported"]
        r = classify(label("20251216", None, spl_unclassified_section=heading), MONTELUKAST)
        self.assertEqual(r["status"], "unparsed")
        # A "WARNING:" heading about something else does not count.
        r = classify(label("20251216", None, spl_unclassified_section=["WARNING: KEEP OUT OF REACH OF CHILDREN"],
                           warnings_and_cautions=["5.4 Neuropsychiatric Events"]), MONTELUKAST)
        self.assertEqual(r["status"], "stale")

    def test_no_prescribing_text(self):
        # Zydus Lifesciences' levofloxacin SPL (ffa121b8..., v11): product data, an empty
        # Medication Guide heading and the bottle label, nothing else.
        hollow = label("20240816", None, spl_product_data_elements=["Levofloxacin ..."],
                       spl_medguide=["SPL MEDGUIDE"],
                       package_label_principal_display_panel=["Levofloxacin Tablets USP, 250 mg Rx only"])
        self.assertFalse(has_text(hollow))
        r = classify(hollow, LEVOFLOXACIN)
        self.assertEqual((r["status"], r["agrees_with"], r["stale_since"], r["days_after_change"]),
                         ("no_text", [], None, None))
        self.assertEqual(r["missing"], [TENDON])
        # Any prescribing section makes the same label a stale copy.
        r = classify(dict(hollow, **TEXT), LEVOFLOXACIN)
        self.assertEqual((r["status"], r["agrees_with"]), ("stale", ["levofloxacin-1996"]))
        self.assertTrue(has_text(dict(hollow, **TEXT)))
        self.assertFalse(has_text(label("2024", warnings=[])))

    def test_current_copy(self):
        r = classify(label("20240101", "WARNING: SERIOUS NEUROPSYCHIATRIC EVENTS"), MONTELUKAST)
        self.assertEqual((r["status"], r["agrees_with"]), ("current", ["montelukast-2020"]))

    def test_older_version_of_a_longer_warning(self):
        box = "WARNING: SERIOUS INFECTIONS, MORTALITY, MALIGNANCY AND THROMBOSIS"
        r = classify(label("20200601", box), TOFACITINIB)
        self.assertEqual((r["status"], r["missing"]), ("stale", ["major adverse cardiovascular events"]))
        self.assertEqual(r["agrees_with"], ["tofacitinib-2019"])
        self.assertEqual(r["stale_since"], dt.date(2021, 12, 2))
        box = "WARNING: SERIOUS INFECTIONS, MORTALITY, MALIGNANCY, MAJOR ADVERSE CARDIOVASCULAR EVENTS (MACE), AND THROMBOSIS"
        self.assertEqual(classify(label("20240601", box), TOFACITINIB)["status"], "current")

    def test_risk_words(self):
        self.assertEqual(risks_in("Lymphoma and other malignancies", ["malignancy", "mortality"]), ["malignancy"])
        self.assertEqual(risks_in("", ["malignancy"]), [])

    def test_label_day(self):
        self.assertEqual(label_day("20200201"), dt.date(2020, 2, 1))
        self.assertIsNone(label_day(""))
        self.assertIsNone(label_day(None))


class AuditTests(unittest.TestCase):
    def test_audit_counts(self):
        history = {"varenicline": VARENICLINE, "levofloxacin": LEVOFLOXACIN}
        records = {
            "varenicline": [label("20200201", "WARNING: SERIOUS NEUROPSYCHIATRIC EVENTS", set_id="a"),
                            label("20230101", set_id="b"),
                            label("20220101", set_id="b", version="0")],
            "levofloxacin": [label("20240101", "WARNING: ... TENDINITIS AND TENDON RUPTURE", set_id="c"),
                             label("20240101", set_id="d", routes=("OPHTHALMIC",)),
                             label("20240816", set_id="e", package_label_principal_display_panel=["Rx only"])],
        }
        rows, summary = audit(records, history)
        self.assertEqual(summary["varenicline"]["labels"], 2)  # set b counted once, at its highest version
        self.assertEqual((summary["varenicline"]["stale"], summary["varenicline"]["current"]), (1, 1))
        self.assertEqual((summary["levofloxacin"]["current"], summary["levofloxacin"]["excluded_route"],
                          summary["levofloxacin"]["no_text"], summary["levofloxacin"]["stale"]), (1, 1, 1, 0))
        self.assertEqual(summary["varenicline"]["newest_version"], "varenicline-2016")
        with tempfile.TemporaryDirectory() as tmp:
            text = write(rows, summary, tmp, {"run_date": "2026-10-14"})
            with open(os.path.join(tmp, "labels.csv"), encoding="utf-8") as f:
                self.assertEqual(len(f.read().splitlines()), 5)
            with open(os.path.join(tmp, "summary.json"), encoding="utf-8") as f:
                self.assertEqual(json.load(f)["drugs"]["varenicline"]["stale"], 1)
        self.assertIn("| varenicline | 2 | 1 | 1 | 0 | 0 | 0 |", text)
        self.assertIn("| levofloxacin | 2 | 1 | 0 | 0 | 1 | 1 |", text)
        self.assertIn("| levofloxacin | Example Labs | 20240816 | e |", text)

    def test_helpers(self):
        self.assertTrue(excluded("levofloxacin", label("2024", routes=("OPHTHALMIC",))))
        self.assertFalse(excluded("levofloxacin", label("2024", routes=("ORAL", "OPHTHALMIC"))))
        self.assertFalse(excluded("montelukast", label("2024", routes=())))
        kept = latest_per_set([label("1", set_id="x", version="2"), label("2", set_id="x", version="10")])
        self.assertEqual([r["version"] for r in kept], ["10"])

    def test_load_history_from_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "h.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump({"versions": list(reversed(VARENICLINE))}, f)
            chains = load_history(path)
        self.assertEqual([x["id"] for x in chains["varenicline"]],
                         ["varenicline-2006", "varenicline-2009", "varenicline-2016"])


if __name__ == "__main__":
    unittest.main()
