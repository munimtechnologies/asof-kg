# audits: checking public drug-label data against asof-kg's dated history

Two standalone scripts, standard library only (Python 3.8+), each with its own unittest file. They need network access to `api.fda.gov` (openFDA allows about 1,000 requests a day without an API key).

| Script | What it does | Output |
|---|---|---|
| `label_sync.py` | For each drug in `asofkg/data/fda_boxed_warnings.json`, it compares every openFDA label copy with the newest FDA-approved boxed warning. Each copy is `current`, `stale` (lacks a required risk or still carries a removed one), `unparsed` (the box is in the text but not in openFDA's `boxed_warning` field) or `no_text` (the label has no prescribing text at all). | `labels.csv`, `summary.json`, `summary.md` |
| `hollow_spl.py` | Finds every human prescription label in openFDA with no indications, dosage or warnings sections. It sorts each into a kind (medical gas, blood-collection solution, drug). For each drug it checks whether other labels of the same generic carry a boxed warning, and whether the labeler or its company family has a full-text label. | `hollow.csv`, `summary.json`, `summary.md`, `facts.json` |

```
python audits/label_sync.py --out out/label-sync
python audits/hollow_spl.py --out out/hollow
python -m unittest discover -s audits -p "test_*.py"
```

Findings from these runs are in [../findings](../findings). openFDA says its data are unvalidated, and a listed label says nothing about the paper insert or what a pharmacy dispenses. Research data, not medical advice.

Code Apache-2.0. Made by MV2 of Munim, Inc. with AI agents (Claude) working in his name.
