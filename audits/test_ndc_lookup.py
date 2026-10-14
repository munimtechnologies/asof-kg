import json
import os
import sys
import tempfile
import unittest
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from ndc_lookup import (classify, load_ndc_directory, marketed, ndc_index, ndcs_of, rows_for,  # noqa: E402
                        summarise, targets, write)

ZYDUS = "Zydus Lifesciences Limited"


def label(set_id, generic, ndcs, boxed="", manufacturer=ZYDUS, kind="drug", status="no_text"):
    return {"set_id": set_id, "manufacturer": manufacturer, "generic_name": generic, "effective_time": "20241128",
            "kind": kind, "text_status": status, "boxed": boxed, "product_ndcs": ndcs}


HOLLOW_CSV = [
    label("dul", "DULOXETINE", "65841-799|65841-800", boxed="yes"),
    label("bos", "BOSENTAN", "70771-1017", boxed="yes"),
    label("acy", "ACYCLOVIR", "70771-1111", boxed="no"),
    label("o2", "OXYGEN", "1234-1", manufacturer="Roberts Oxygen Company, Inc.", kind="gas"),
    label("efu", "FLUOROURACIL", "0187-3204", manufacturer="Bausch Health US, LLC", status="uncoded_text"),
    label("nondc", "IBUPROFEN", "", manufacturer="Example Rx"),
]
LOOKUPS = {"65841-799": ["dul"], "65841-800": ["dul"], "70771-1017": ["bos"], "70771-1111": ["acy", "zpusa"]}
INDEX = {"65841-799": {"product_ndc": "65841-799", "marketing_category": "ANDA", "marketing_start_date": "20140527",
                       "listing_expiration_date": "20271231"},
         "70771-1017": {"product_ndc": "70771-1017", "marketing_category": "ANDA",
                        "marketing_start_date": "20190501", "marketing_end_date": "20250101"}}


class UnitTests(unittest.TestCase):
    def test_classify(self):
        hollow = {"h1", "h2"}
        self.assertEqual(classify(None, hollow), "lookup_failed")
        self.assertEqual(classify([], hollow), "not_found")
        self.assertEqual(classify(["h1"], hollow), "dead_end")
        self.assertEqual(classify(["h1", "h2"], hollow), "dead_end")
        self.assertEqual(classify(["h1", "x"], hollow), "full_text_elsewhere")

    def test_targets_and_ndcs(self):
        labels, hollow_ids = targets(HOLLOW_CSV)
        self.assertEqual([r["set_id"] for r in labels], ["dul", "bos", "acy", "nondc"])
        self.assertEqual(hollow_ids, {"dul", "bos", "acy", "o2", "nondc"})
        self.assertEqual(ndcs_of(HOLLOW_CSV[0]), ["65841-799", "65841-800"])
        self.assertEqual(ndcs_of(HOLLOW_CSV[5]), [])
        self.assertEqual(ndcs_of({}), [])

    def test_ndc_directory(self):
        self.assertEqual(sorted(ndc_index([{"product_ndc": "1-1", "a": 1}, {"x": 2}])), ["1-1"])
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(load_ndc_directory(tmp), [])
            with zipfile.ZipFile(os.path.join(tmp, "drug-ndc-0001-of-0001.json.zip"), "w") as z:
                z.writestr("drug-ndc-0001-of-0001.json", json.dumps({"results": [{"product_ndc": "65841-799"}]}))
            self.assertEqual(load_ndc_directory(tmp), [{"product_ndc": "65841-799"}])

    def test_marketed(self):
        self.assertTrue(marketed({"in_ndc_directory": "yes", "marketing_end_date": ""}, "20261014"))
        self.assertTrue(marketed({"in_ndc_directory": "yes", "marketing_end_date": "20261231"}, "20261014"))
        self.assertFalse(marketed({"in_ndc_directory": "yes", "marketing_end_date": "20250101"}, "20261014"))
        self.assertFalse(marketed({"in_ndc_directory": "no", "marketing_end_date": ""}, "20261014"))


class RunTests(unittest.TestCase):
    def test_rows_summary_and_write(self):
        labels, hollow_ids = targets(HOLLOW_CSV)
        rows = [row for lab in labels for row in rows_for(lab, LOOKUPS, INDEX, hollow_ids)]
        self.assertEqual([(r["set_id"], r["product_ndc"], r["status"], r["in_ndc_directory"]) for r in rows], [
            ("dul", "65841-799", "dead_end", "yes"),
            ("dul", "65841-800", "dead_end", "no"),
            ("bos", "70771-1017", "dead_end", "yes"),
            ("acy", "70771-1111", "full_text_elsewhere", "no"),
            ("nondc", "", "no_ndc", "no"),
        ])
        self.assertEqual((rows[0]["dailymed_set_ids"], rows[3]["dailymed_set_ids"]), ("dul", "acy|zpusa"))
        self.assertEqual((rows[2]["marketing_end_date"], rows[0]["listing_expiration_date"]), ("20250101", "20271231"))
        bare = rows_for(labels[1], LOOKUPS, {}, hollow_ids)[0]
        self.assertEqual((bare["status"], bare["in_ndc_directory"], bare["marketing_category"]), ("dead_end", "", ""))
        failed = rows_for(labels[1], {"70771-1017": None}, {}, hollow_ids)[0]
        self.assertEqual((failed["status"], failed["dailymed_set_ids"]), ("lookup_failed", ""))

        s = summarise(rows, "20261014")
        self.assertEqual((s["labels"], s["product_ndcs"]), (4, 5))
        self.assertEqual(s["ndcs_by_status"], {"dead_end": 3, "full_text_elsewhere": 1, "no_ndc": 1})
        self.assertEqual(s["labels_whose_every_ndc_is_a_dead_end"], 2)
        self.assertEqual(s["dead_end_labels_by_labeler"], {ZYDUS: 2})
        self.assertEqual(s["boxed_labels_whose_every_ndc_is_a_dead_end"], 2)
        self.assertEqual((s["dead_end_ndcs_in_ndc_directory"], s["dead_end_ndcs_marketed"]), (2, 1))
        self.assertEqual(s["boxed_dead_end_set_ids"], ["bos", "dul"])

        with tempfile.TemporaryDirectory() as tmp:
            text = write(rows, s, tmp, {"run_date": "2026-10-14", "today": "20261014", "note": ""})
            with open(os.path.join(tmp, "ndc.csv"), encoding="utf-8") as f:
                self.assertEqual(len(f.read().splitlines()), 6)
            with open(os.path.join(tmp, "summary.json"), encoding="utf-8") as f:
                self.assertEqual(json.load(f)["summary"]["labels"], 4)
        self.assertIn("- Hollow drug labels looked up: 4", text)
        self.assertIn("- Product NDCs: 5 (dead_end 3, full_text_elsewhere 1, no_ndc 1)", text)
        self.assertIn("- Labels whose every NDC leads only to hollow labels on DailyMed: 2", text)
        self.assertIn("- ... of them for a drug whose labels mostly carry a boxed warning: 2", text)
        self.assertIn("- Dead-end NDCs in FDA's NDC Directory: 2, of which still marketed on 20261014: 1", text)
        self.assertIn("| Zydus Lifesciences Limited | 2 |", text)
        self.assertIn("| BOSENTAN | Zydus Lifesciences Limited | bos | 70771-1017 |", text)
        self.assertIn("| DULOXETINE | Zydus Lifesciences Limited | dul | 65841-799, 65841-800 |", text)
        self.assertNotIn("Note:", text)
        self.assertLess(text.index("| BOSENTAN"), text.index("| DULOXETINE"))


if __name__ == "__main__":
    unittest.main()
