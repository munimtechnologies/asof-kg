import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from hollow_spl import HOLLOW, family, is_hollow, kind_of, latest_per_set, quote, row_for, sections, summarise, write  # noqa: E402


def record(generic, manufacturer, set_id="s1", version="1", effective="20240816", **content):
    r = {"set_id": set_id, "id": "i-" + set_id, "version": version, "effective_time": effective,
         "openfda": {"generic_name": [generic], "manufacturer_name": [manufacturer], "brand_name": [generic.lower()],
                     "route": ["ORAL"], "product_type": ["HUMAN PRESCRIPTION DRUG"]},
         "spl_product_data_elements": [generic], "package_label_principal_display_panel": ["Rx only"]}
    r.update(content)
    return r


FACTS = {
    "LEVOFLOXACIN": {"boxed": 70, "boxed_labelers": ["A Labs", "B Pharma"],
                     "full_text_labelers": ["A Labs", "B Pharma"]},
    "METFORMIN HYDROCHLORIDE": {"boxed": 0, "boxed_labelers": [],
                                "full_text_labelers": ["Zydus Pharmaceuticals USA Inc.", "A Labs"]},
    "TOFACITINIB": {"boxed": 20, "boxed_labelers": ["A Labs"],
                    "full_text_labelers": ["A Labs", "Zydus Pharmaceuticals USA Inc."]},
}


class KindTests(unittest.TestCase):
    def test_kind_of(self):
        self.assertEqual(kind_of("OXYGEN"), "gas")
        self.assertEqual(kind_of("CARBON DIOXIDE-OXYGEN-NITROGEN MIXTURE"), "gas")
        self.assertEqual(kind_of("AIR COMPRESSED"), "gas")
        self.assertEqual(kind_of("Nitrous Oxide"), "gas")
        self.assertEqual(kind_of("ANTICOAGULANT CITRATE PHOSPHATE DEXTROSE ADENINE"), "blood")
        self.assertEqual(kind_of("CP2D/AS-3 ANTICOAGULANT AND ADDITIVE SYSTEM"), "blood")
        self.assertEqual(kind_of("LEVOFLOXACIN"), "drug")
        self.assertEqual(kind_of("NITROGLYCERIN"), "drug")
        self.assertEqual(kind_of("SODIUM CHLORIDE"), "drug")

    def test_family(self):
        self.assertEqual(family("Zydus Lifesciences Limited"), family("Zydus Pharmaceuticals USA Inc."))
        self.assertEqual(family("NuCare Pharmaceuticals,Inc."), "nucare")
        self.assertEqual(family(""), "")

    def test_hollow_and_sections(self):
        hollow = record("LEVOFLOXACIN", "Zydus Lifesciences Limited", spl_medguide=["SPL MEDGUIDE"])
        self.assertTrue(is_hollow(hollow))
        self.assertEqual(sections(hollow), ["package_label_principal_display_panel", "spl_medguide",
                                            "spl_product_data_elements"])
        self.assertFalse(is_hollow(record("LEVOFLOXACIN", "A Labs", indications_and_usage=["1 INDICATIONS"])))
        self.assertFalse(is_hollow(record("LEVOFLOXACIN", "A Labs", boxed_warning=["WARNING: ..."])))
        self.assertTrue(is_hollow(record("LEVOFLOXACIN", "A Labs", warnings=[])))

    def test_query(self):
        self.assertTrue(HOLLOW.startswith('openfda.product_type:"HUMAN PRESCRIPTION DRUG" AND _missing_:'))
        self.assertEqual(HOLLOW.count("_missing_:"), 4)
        self.assertEqual(quote('A "B" C'), '"A B C"')

    def test_latest_per_set(self):
        kept = latest_per_set([record("X", "M", set_id="a", version="2"), record("X", "M", set_id="a", version="11"),
                               record("X", "M", set_id="b", version="1")])
        self.assertEqual(sorted((r["set_id"], r["version"]) for r in kept), [("a", "11"), ("b", "1")])


class RowTests(unittest.TestCase):
    def test_rows_and_summary(self):
        records = [
            record("LEVOFLOXACIN", "Zydus Lifesciences Limited", set_id="lev"),        # boxed, no family text
            record("TOFACITINIB", "Zydus Lifesciences Limited", set_id="tof"),         # boxed, family has text
            record("METFORMIN HYDROCHLORIDE", "Zydus Lifesciences Limited", set_id="met"),  # no boxed warning
            record("OXYGEN", "Roberts Oxygen Company, Inc.", set_id="o2"),
            record("ANTICOAGULANT CITRATE PHOSPHATE DEXTROSE ADENINE", "Fenwal, Inc.", set_id="cpd"),
            record("IBUPROFEN", "Example Rx", set_id="ibu"),                          # no facts fetched
        ]
        rows = [row_for(r, FACTS) for r in records]
        by_id = {r["set_id"]: r for r in rows}
        self.assertEqual((by_id["lev"]["kind"], by_id["lev"]["boxed_labels_of_generic"],
                          by_id["lev"]["boxed_labelers_of_generic"]), ("drug", 70, 2))
        self.assertEqual((by_id["lev"]["labeler_has_full_text"], by_id["lev"]["family_has_full_text"]), ("no", "no"))
        self.assertEqual((by_id["tof"]["labeler_has_full_text"], by_id["tof"]["family_has_full_text"]), ("no", "yes"))
        self.assertEqual(by_id["met"]["boxed_labels_of_generic"], 0)
        self.assertEqual((by_id["o2"]["kind"], by_id["o2"]["boxed_labels_of_generic"]), ("gas", ""))
        self.assertEqual(by_id["cpd"]["kind"], "blood")
        self.assertEqual((by_id["ibu"]["kind"], by_id["ibu"]["boxed_labels_of_generic"]), ("drug", ""))

        s = summarise(rows, 35865)
        self.assertEqual((s["rx_labels"], s["hollow_labels"]), (35865, 6))
        self.assertEqual(s["by_kind"], {"drug": 4, "gas": 1, "blood": 1})
        self.assertEqual(s["drug_labels_by_labeler"], {"Zydus Lifesciences Limited": 3, "Example Rx": 1})
        self.assertEqual(s["hollow_drug_labels_whose_generic_has_a_boxed_warning"], 2)
        self.assertEqual(s["of_which_no_full_text_label_from_the_same_company_family"], 1)
        self.assertEqual(s["boxed_by_labeler"], {"Zydus Lifesciences Limited": 2})
        self.assertEqual(s["boxed_generics"], ["LEVOFLOXACIN", "TOFACITINIB"])
        self.assertEqual(s["orphan_set_ids"], ["lev"])

        with tempfile.TemporaryDirectory() as tmp:
            text = write(rows, s, tmp, {"run_date": "2026-10-14"})
            with open(os.path.join(tmp, "hollow.csv"), encoding="utf-8") as f:
                self.assertEqual(len(f.read().splitlines()), 7)
            with open(os.path.join(tmp, "summary.json"), encoding="utf-8") as f:
                self.assertEqual(json.load(f)["summary"]["hollow_labels"], 6)
        self.assertIn("- Hollow (no indications, dosage, warnings or boxed warning): 6", text)
        self.assertIn("| Zydus Lifesciences Limited | 3 | 2 |", text)
        self.assertIn("| Example Rx | 1 | 0 |", text)
        self.assertIn("| LEVOFLOXACIN | Zydus Lifesciences Limited | 20240816 | lev | no |", text)
        self.assertIn("- By kind: blood 1, drug 4, gas 1", text)


if __name__ == "__main__":
    unittest.main()
