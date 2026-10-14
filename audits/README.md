# audits: checking public drug-label data against asof-kg's dated history

Standalone scripts, standard library only (Python 3.8+), each with its own unittest file. They need network access: `api.fda.gov` (openFDA allows about 1,000 requests a day without an API key) and, for `ndc_lookup.py`, `dailymed.nlm.nih.gov` and `download.open.fda.gov`.

| Script | What it does | Output |
|---|---|---|
| `label_sync.py` | For each drug in `asofkg/data/fda_boxed_warnings.json`, it compares every openFDA label copy with the newest FDA-approved boxed warning. Each copy is `current`, `stale` (lacks a required risk or still carries a removed one), `unparsed` (the box is in the text but not in openFDA's `boxed_warning` field) or `no_text` (the label has no prescribing text at all). | `labels.csv`, `summary.json`, `summary.md` |
| `hollow_spl.py` | Finds every human prescription label in openFDA with no indications, dosage or warnings sections. It separates labels whose text sits in unclassified sections (`uncoded_text`) from labels with no text at all (`no_text`), and sorts each into a kind (medical gas, blood-collection solution, drug). For each drug it checks whether most full-text labels of the same generic **and route** carry a boxed warning, whether the labeler or its company family has a full-text label, and who has full text under the same application number. | `hollow.csv`, `summary.json`, `summary.md`, `facts.json` |
| `ndc_lookup.py` | Takes `hollow.csv` and looks up each hollow drug label's product NDCs on DailyMed. An NDC is a `dead_end` when every SPL DailyMed lists for it is hollow. It also adds marketing dates from FDA's NDC Directory. | `ndc.csv`, `summary.json`, `summary.md` |

```
python audits/label_sync.py --out out/label-sync
python audits/hollow_spl.py --out out/hollow
python audits/ndc_lookup.py --hollow out/hollow/hollow.csv --out out/ndc
python -m unittest discover -s audits -p "test_*.py"
```

Findings from these runs are in [../findings](../findings). openFDA says its data are unvalidated, and a listed label says nothing about the paper insert or what a pharmacy dispenses. Research data, not medical advice.

Code Apache-2.0. Made by MV2 of Munim, Inc. with AI agents (Claude) working in his name.
