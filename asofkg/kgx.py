"""Write the graph as KGX nodes and edges TSV files, as it could be known on a given day.

KGX is the exchange format of the Biolink Model, used by the NCATS
Biomedical Data Translator. Each version of a guideline, drug label or case
definition is a node (biolink:Publication or biolink:InformationContentEntity)
that biolink:mentions the condition, drug or procedure it is about, and is
linked to the version it revises. A drug's boxed-warning risks that map to
MeSH become biolink:has_adverse_event edges, one per span of time the risk
stayed in the boxed warning.

Biolink has no slots for valid time and knowledge time, so they are extra
columns, as KGX allows:

- ``valid_from``, ``valid_to``: when a version was in force, or a risk was
  in the boxed warning (``valid_to`` exclusive, empty while open).
- ``known_from``: when that could first be known in the chosen view.
- ``valid_to_known_from``: when the end could first be known (edges).

A snapshot holds only what was known on ``known_at``, so an end appears only
once the version that brings it is known.
"""

import datetime as dt
import os

from .instants import as_date
from .versions import fact_spans

SOURCE = "infores:asof-kg"  # not (yet) in the Biolink information resource registry
INSTANCE = "biolink:related_to_at_instance_level"
NODE_COLUMNS = ("id", "category", "name", "xref", "valid_from", "valid_to", "known_from", "provided_by")
EDGE_COLUMNS = ("id", "subject", "predicate", "object", "original_predicate", "knowledge_level", "agent_type",
                "primary_knowledge_source", "publications", "description",
                "valid_from", "valid_to", "known_from", "valid_to_known_from")


def _local(curie):
    return curie.split(":", 1)[1]


def _day(day):
    return "" if day is None else day.isoformat()


def _node(nodes, curie, category, name, **extra):
    if curie not in nodes:
        row = {"id": curie, "category": category, "name": name, "provided_by": SOURCE}
        row.update(extra)
        nodes[curie] = row
    return curie


def _edge(edges, curie, subject, predicate, obj, **extra):
    row = {"id": curie, "subject": subject, "predicate": predicate, "object": obj,
           "knowledge_level": "knowledge_assertion", "agent_type": "manual_agent",
           "primary_knowledge_source": SOURCE}
    row.update(extra)
    edges.append(row)


def _version_node(nodes, version, category, span, known_from):
    start, end = span
    return _node(nodes, "akgd:" + version.id, category, version.title,
                 valid_from=_day(start), valid_to=_day(end), known_from=_day(known_from))


def to_kgx(kg, labels, casedefs, known_at=None, view="public"):
    """KGX nodes and edges, as lists of dicts, for everything known by ``known_at`` (default: everything)."""
    known_at = dt.date.max if known_at is None else as_date(known_at)
    nodes, edges = {}, []

    for v in kg.versions:
        span = kg.interval(v.id, known_at)
        if span is None:
            continue
        node = _version_node(nodes, v, "biolink:Publication", span, v.published.latest)
        nodes[node]["xref"] = "PMID:" + v.pmid
        info = kg.topic_info.get(v.topic, {})
        for key in ("condition", "intervention"):
            if info.get(key):
                target = _node(nodes, info[key], info.get(key + "_category", "biolink:NamedThing"),
                               info.get(key + "_label", info[key]))
                _edge(edges, "akgd:%s-mentions-%s" % (v.id, _local(target)), node, "biolink:mentions", target)
        if v.supersedes in kg.by_id and kg.interval(v.supersedes, known_at) is not None:
            _edge(edges, "akgd:%s-revises-%s" % (v.id, v.supersedes), node, INSTANCE, "akgd:" + v.supersedes,
                  original_predicate="prov:wasRevisionOf")

    for chains in (labels, casedefs):
        for v in chains.versions:
            span = chains.interval(v.id, known_at, view)
            if span is None:
                continue
            node = _version_node(nodes, v, "biolink:InformationContentEntity", span, v.known_from(view).latest)
            info = chains.subject_info.get(v.subject, {})
            targets = []
            if info.get("rxcui"):
                targets.append(_node(nodes, "RXNORM:" + info["rxcui"], "biolink:Drug", v.subject))
            if info.get("condition"):
                targets.append(_node(nodes, info["condition"], "biolink:Disease",
                                     info.get("condition_label", info["condition"])))
            for target in targets:
                _edge(edges, "akgd:%s-mentions-%s" % (v.id, _local(target)), node, "biolink:mentions", target)
            if v.supersedes in chains.by_id and chains.interval(v.supersedes, known_at, view) is not None:
                _edge(edges, "akgd:%s-revises-%s" % (v.id, v.supersedes), node, INSTANCE, "akgd:" + v.supersedes,
                      original_predicate="prov:wasRevisionOf")
            if v.facts.get("evidence_pmid"):
                trial = _node(nodes, "PMID:" + v.facts["evidence_pmid"], "biolink:Publication",
                              "PMID:" + v.facts["evidence_pmid"])
                _edge(edges, "akgd:%s-evidence-%s" % (v.id, _local(trial)), node, INSTANCE, trial,
                      original_predicate="prov:wasInfluencedBy")

    for span in fact_spans(labels, "boxed_warning", known_at, view):
        rxcui = labels.subject_info.get(span["subject"], {}).get("rxcui")
        if not rxcui:
            continue
        evidence = labels.by_id[span["started_by"]].facts.get("evidence_pmid")
        for term in labels.terms.get(span["value"], []):
            drug = _node(nodes, "RXNORM:" + rxcui, "biolink:Drug", span["subject"])
            target = _node(nodes, term["id"], "biolink:DiseaseOrPhenotypicFeature", term["label"])
            _edge(edges, "akgd:%s-ae-%s-%s" % (span["subject"], _local(target), _day(span["start"])),
                  drug, "biolink:has_adverse_event", target,
                  publications="PMID:" + evidence if evidence else "",
                  description="boxed warning: " + span["value"],
                  valid_from=_day(span["start"]), valid_to=_day(span["end"]),
                  known_from=_day(span["start_known_from"]), valid_to_known_from=_day(span["end_known_from"]))

    return list(nodes.values()), edges


def _cell(value):
    if isinstance(value, (list, tuple)):
        value = "|".join(value)
    return str(value).replace("\t", " ").replace("\r", " ").replace("\n", " ")


def write_kgx(nodes, edges, directory):
    """Write ``nodes.tsv`` and ``edges.tsv`` into ``directory``; returns their two paths."""
    os.makedirs(directory, exist_ok=True)
    paths = []
    for name, rows, columns in (("nodes.tsv", nodes, NODE_COLUMNS), ("edges.tsv", edges, EDGE_COLUMNS)):
        path = os.path.join(directory, name)
        with open(path, "w", encoding="utf-8", newline="") as f:
            f.write("\t".join(columns) + "\n")
            for row in rows:
                f.write("\t".join(_cell(row.get(column, "")) for column in columns) + "\n")
        paths.append(path)
    return paths
