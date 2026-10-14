import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from hollow_spl import (HOLLOW, RX, boxed_share, family, free_text, is_candidate, kind_of,  # noqa: E402
                        latest_per_set, quote, row_for, scope, sections, summarise, text_status, write)


def record(generic, manufacturer, set_id="s1", version="1", effective="20240816", route="ORAL",
           app="ANDA000001", ndc="70771-0001", **content):
    r = {"set_id": set_id, "id": "i-" + set_id, "version": version, "effective_time": effective,
         "openfda": {"generic_name": [generic], "manufacturer_name": [manufacturer], "brand_name": [generic.lower()],
                     "route": [route], "application_number": [app], "product_type": ["HUMAN PRESCRIPTION DRUG"],
                     "product_ndc": [ndc]},
         "spl_product_data_elements": [generic], "package_label_principal_display_panel": ["Rx only"]}
    r.update(content)
    return r


ZYDUS = "Zydus Lifesciences Limited"
FACTS = {
    "LEVOFLOXACIN|ORAL": {"boxed": {"A Labs": 40, "B Pharma": 30}, "full_text": {"A Labs": 40, "B Pharma": 32}},
    "TOFACITINIB|ORAL": {"boxed": {"A Labs": 20, "Zydus Pharmaceuticals USA Inc.": 1},
                         "full_text": {"A Labs": 20, "Zydus Pharmaceuticals USA Inc.": 1}},
    "AZITHROMYCIN|ORAL": {"boxed": {"Proficient Rx LP": 1}, "full_text": {"A Labs": 50, ZYDUS: 1}},
    "TRETINOIN|TOPICAL": {"boxed": {}, "full_text": {"A Labs": 10}},
    "METFORMIN HYDROCHLORIDE|ORAL": {"boxed": {}, "full_text": None},
}
APP_TEXT = {"ANDA077652": ["A Labs"]}


class KindTests(unittest.TestCase):
    def test_kind_of(self):
        self.assertEqual(kind_of("OXYGEN"), "gas")
        self.assertEqual(kind_of("CARBON DIOXIDE-OXYGEN-NITROGEN MIXTURE"), "gas")
        self.assertEqual(kind_of("Nitrous Oxide"), "gas")
        self.assertEqual(kind_of("ANTICOAGULANT CITRATE PHOSPHATE DEXTROSE ADENINE"), "blood")
        self.assertEqual(kind_of("LEVOFLOXACIN"), "drug")
        self.assertEqual(kind_of("SODIUM CHLORIDE"), "drug")

    def test_kind_of_gas_mixtures(self):
        # Version 2.0 filed these 34 gas labels as drugs.
        for name in ("OXYGEN/HELIUM 20/80", "OXYGEN/NITROGEN 9.7/90.3", "AIR 90% CARBON DIOXIDE 10%",
                     "40% OXYGEN/NITROGEN MIX", "OXYGEN, COMPRESSED U.S.P.", "BREATHING AIR", "OXYGEN GAS",
                     "OXYGEN REFRIGERATED LIQUID", "NITROGEN, REFRIGERATED", "0XYGEN"):
            self.assertEqual(kind_of(name), "gas", name)
        self.assertEqual(kind_of("10"), "drug")
        self.assertEqual(kind_of("NITRIC OXIDE"), "drug")
        self.assertEqual(kind_of(""), "drug")

    def test_family(self):
        self.assertEqual(family(ZYDUS), family("Zydus Pharmaceuticals USA Inc."))
        self.assertEqual(family("NuCare Pharmaceuticals,Inc."), "nucare")
        self.assertEqual(family(""), "")

    def test_candidate_and_text(self):
        empty = record("LEVOFLOXACIN", ZYDUS, spl_medguide=["SPL MEDGUIDE"])
        self.assertTrue(is_candidate(empty))
        self.assertEqual(free_text(empty), 12)
        self.assertEqual(text_status(empty), "no_text")
        self.assertEqual(sections(empty), ["package_label_principal_display_panel", "spl_medguide",
                                           "spl_product_data_elements"])
        uncoded = record("FLUOROURACIL", "Bausch Health US, LLC", route="TOPICAL",
                         spl_unclassified_section=["INDICATIONS AND USAGE: " + "x" * 300])
        self.assertTrue(is_candidate(uncoded))
        self.assertEqual(free_text(uncoded), 323)
        self.assertEqual(text_status(uncoded), "uncoded_text")
        self.assertEqual(free_text(record("X", "M", spl_unclassified_section=["  abc  "],
                                          spl_medguide_table=["long" * 100])), 3)
        self.assertFalse(is_candidate(record("LEVOFLOXACIN", "A Labs", indications_and_usage=["1 INDICATIONS"])))
        self.assertFalse(is_candidate(record("LEVOFLOXACIN", "A Labs", boxed_warning=["WARNING: ..."])))
        self.assertTrue(is_candidate(record("LEVOFLOXACIN", "A Labs", warnings=[])))

    def test_queries(self):
        self.assertTrue(HOLLOW.startswith('openfda.product_type:"HUMAN PRESCRIPTION DRUG" AND _missing_:'))
        self.assertEqual(HOLLOW.count("_missing_:"), 5)
        self.assertEqual(quote('A "B" C'), '"A B C"')
        self.assertEqual(scope("LEVOFLOXACIN", "ORAL"),
                         RX + ' AND openfda.generic_name.exact:"LEVOFLOXACIN" AND openfda.route.exact:"ORAL"')
        self.assertEqual(scope("LEVOFLOXACIN", ""), RX + ' AND openfda.generic_name.exact:"LEVOFLOXACIN"')

    def test_boxed_share(self):
        self.assertEqual(boxed_share({"boxed": {"A": 3}, "full_text": {"A": 4, "B": 2}}), 0.5)
        self.assertEqual(boxed_share({"boxed": {"A": 1}, "full_text": None}), 1.0)
        self.assertEqual(boxed_share({"boxed": {}, "full_text": None}), 0.0)
        self.assertEqual(boxed_share({"boxed": {"A": 9}, "full_text": {"A": 4}}), 1.0)

    def test_latest_per_set(self):
        kept = latest_per_set([record("X", "M", set_id="a", version="2"), record("X", "M", set_id="a", version="11"),
                               record("X", "M", set_id="b", version="1")])
        self.assertEqual(sorted((r["set_id"], r["version"]) for r in kept), [("a", "11"), ("b", "1")])


class RowTests(unittest.TestCase):
    def test_rows_and_summary(self):
        records = [
            record("LEVOFLOXACIN", ZYDUS, set_id="lev", app="ANDA077652", ndc="70771-1001"),  # boxed, no family text
            record("TOFACITINIB", ZYDUS, set_id="tof", app="ANDA111111"),   # boxed, family has text
            record("AZITHROMYCIN", ZYDUS, set_id="azi"),                    # one stray box: not boxed
            record("TRETINOIN", ZYDUS, set_id="tre", route="TOPICAL"),      # no box on the topical route
            record("METFORMIN HYDROCHLORIDE", ZYDUS, set_id="met"),         # not a candidate in v1: unboxed
            record("OXYGEN", "Roberts Oxygen Company, Inc.", set_id="o2", route="RESPIRATORY (INHALATION)"),
            record("ANTICOAGULANT CITRATE PHOSPHATE DEXTROSE ADENINE", "Fenwal, Inc.", set_id="cpd"),
            record("FLUOROURACIL", "Bausch Health US, LLC", set_id="efu", route="TOPICAL",
                   spl_unclassified_section=["INDICATIONS AND USAGE: " + "x" * 300]),
            record("IBUPROFEN", "Example Rx", set_id="ibu"),                # no facts fetched
        ]
        rows = [row_for(r, FACTS, APP_TEXT) for r in records]
        by_id = {r["set_id"]: r for r in rows}
        lev = by_id["lev"]
        self.assertEqual((lev["kind"], lev["text_status"], lev["boxed_labels"], lev["full_text_labels"],
                          lev["boxed_share"], lev["boxed"]), ("drug", "no_text", 70, 72, 0.972, "yes"))
        self.assertEqual((lev["labeler_has_full_text"], lev["family_has_full_text"],
                          lev["same_application_full_text"]), ("no", "no", "A Labs"))
        self.assertEqual((lev["product_ndcs"], by_id["o2"]["product_ndcs"]), ("70771-1001", "70771-0001"))
        tof = by_id["tof"]
        self.assertEqual((tof["boxed_share"], tof["boxed"], tof["labeler_has_full_text"], tof["family_has_full_text"],
                          tof["same_application_full_text"]), (1.0, "yes", "no", "yes", ""))
        self.assertEqual((by_id["azi"]["boxed_share"], by_id["azi"]["boxed"], by_id["azi"]["labeler_has_full_text"]),
                         (0.02, "no", "yes"))
        self.assertEqual((by_id["tre"]["boxed_share"], by_id["tre"]["boxed"], by_id["tre"]["family_has_full_text"]),
                         (0.0, "no", "no"))
        met = by_id["met"]
        self.assertEqual((met["boxed_labels"], met["boxed"], met["full_text_labels"], met["family_has_full_text"]),
                         (0, "no", "", ""))
        self.assertEqual((by_id["o2"]["kind"], by_id["o2"]["boxed"]), ("gas", ""))
        self.assertEqual(by_id["cpd"]["kind"], "blood")
        self.assertEqual((by_id["efu"]["text_status"], by_id["efu"]["free_text_chars"], by_id["efu"]["boxed"]),
                         ("uncoded_text", 323, ""))
        self.assertEqual((by_id["ibu"]["kind"], by_id["ibu"]["boxed"]), ("drug", ""))

        s = summarise(rows, 35865, {ZYDUS: 265, "Fenwal, Inc.": 40})
        self.assertEqual((s["rx_labels"], s["candidates"], s["uncoded_text"], s["hollow_labels"]), (35865, 9, 1, 8))
        self.assertEqual(s["by_kind"], {"drug": 6, "gas": 1, "blood": 1})
        self.assertEqual(s["drug_labels_by_labeler"], {ZYDUS: 5, "Example Rx": 1})
        self.assertEqual(s["rx_labels_of_labeler"], {ZYDUS: 265, "Example Rx": 0})
        self.assertEqual(s["hollow_drug_labels_with_boxed_warning_drug"], 2)
        self.assertEqual(s["of_which_no_full_text_label_from_the_same_company_family"], 1)
        self.assertEqual(s["boxed_by_labeler"], {ZYDUS: 2})
        self.assertEqual(s["boxed_generics"], ["LEVOFLOXACIN", "TOFACITINIB"])
        self.assertEqual((s["orphan_set_ids"], s["uncoded_set_ids"]), (["lev"], ["efu"]))

        with tempfile.TemporaryDirectory() as tmp:
            text = write(rows, s, tmp, {"run_date": "2026-10-14"})
            with open(os.path.join(tmp, "hollow.csv"), encoding="utf-8") as f:
                lines = f.read().splitlines()
            self.assertEqual(len(lines), 10)
            self.assertTrue(lines[0].endswith(",same_application_full_text,product_ndcs"))
            with open(os.path.join(tmp, "summary.json"), encoding="utf-8") as f:
                self.assertEqual(json.load(f)["summary"]["hollow_labels"], 8)
        self.assertIn("- With no indications, dosage, warnings or boxed-warning section: 9", text)
        self.assertIn("- ... of which the text sits in unclassified sections (not hollow): 1", text)
        self.assertIn("- Hollow (at most 200 characters of text besides product data and package label): 8", text)
        self.assertIn("- Hollow by kind: blood 1, drug 6, gas 1", text)
        self.assertIn("| Zydus Lifesciences Limited | 5 | 265 | 2 |", text)
        self.assertIn("| Example Rx | 1 | 0 | 0 |", text)
        self.assertIn("| LEVOFLOXACIN | ORAL | Zydus Lifesciences Limited | 20240816 | lev | 0.972 | no | A Labs |", text)
        self.assertIn("| TOFACITINIB | ORAL | Zydus Lifesciences Limited | 20240816 | tof | 1.0 | yes | - |", text)
        self.assertIn("| FLUOROURACIL | Bausch Health US, LLC | efu | 323 |", text)
        self.assertNotIn("| AZITHROMYCIN | ORAL", text)


if __name__ == "__main__":
    unittest.main()
