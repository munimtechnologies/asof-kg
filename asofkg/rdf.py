"""Write the graph as Turtle, as it could be known on a given day."""

import datetime as dt

from .instants import as_date

PREFIXES = """@prefix akg: <https://github.com/munimtechnologies/asof-kg/ontology#> .
@prefix akgd: <https://github.com/munimtechnologies/asof-kg/data#> .
@prefix biolink: <https://w3id.org/biolink/vocab/> .
@prefix MESH: <http://id.nlm.nih.gov/mesh/> .
@prefix obo: <http://purl.obolibrary.org/obo/> .
@prefix prov: <http://www.w3.org/ns/prov#> .
@prefix pubmed: <https://pubmed.ncbi.nlm.nih.gov/> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix RXNORM: <http://purl.bioontology.org/ontology/RXNORM/> .
@prefix time: <http://www.w3.org/2006/time#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
"""

SEX = {"female": "obo:PATO_0000383", "male": "obo:PATO_0000384"}


def _literal(text):
    return '"%s"' % text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def _date(day):
    return '"%s"^^xsd:date' % day.isoformat()


def _iri(url):
    return "<%s>" % url.replace(" ", "%20").replace(">", "%3E")


def _interval(lines, node, start, end):
    lines.append("%s-interval a time:ProperInterval ;" % node)
    if end is None:
        lines.append("    time:hasBeginning [ a time:Instant ; time:inXSDDate %s ] ." % _date(start))
    else:
        lines.append("    time:hasBeginning [ a time:Instant ; time:inXSDDate %s ] ;" % _date(start))
        lines.append("    time:hasEnd [ a time:Instant ; time:inXSDDate %s ] ." % _date(end))
    lines.append("")


def to_turtle(kg, known_at=None):
    """Turtle for every version published by ``known_at`` (default: everything).

    Intervals are written as they could be known on ``known_at``: a version
    whose successor was not yet published gets no time:hasEnd.
    """
    known_at = dt.date.max if known_at is None else as_date(known_at)
    lines = [PREFIXES]
    if known_at != dt.date.max:
        lines.append("# Snapshot: only what was published by %s.\n" % known_at.isoformat())
    topics = []
    for v in kg.versions:
        span = kg.interval(v.id, known_at)
        if span is None:
            continue
        if v.topic not in topics:
            topics.append(v.topic)
        start, end = span
        node = "akgd:" + v.id
        lines.append("%s a akg:GuidelineVersion ;" % node)
        lines.append("    rdfs:label %s@en ;" % _literal(v.title))
        lines.append("    akg:topic akgd:%s ;" % v.topic)
        lines.append("    akg:publishedOn %s ;" % _date(v.published.latest))
        if v.supersedes in kg.by_id:
            lines.append("    akg:supersedes akgd:%s ;" % v.supersedes)
        lines.append("    prov:wasDerivedFrom pubmed:%s ;" % v.pmid)
        lines.append("    akg:inForceDuring %s-interval ." % node)
        lines.append("")
        _interval(lines, node, start, end)
        for i, rec in enumerate(v.recommendations, 1):
            lines.append("%s-r%d a akg:Recommendation ;" % (node, i))
            lines.append("    akg:partOfGuideline %s ;" % node)
            if rec.sex is not None:
                lines.append("    akg:sex %s ;" % SEX[rec.sex])
            if rec.age_min is not None:
                lines.append("    akg:minAge %d ;" % rec.age_min)
            if rec.age_max is not None:
                lines.append("    akg:maxAge %d ;" % rec.age_max)
            if rec.min_cvd_risk_10y is not None:
                lines.append('    akg:minTenYearCvdRisk "%s"^^xsd:decimal ;' % rec.min_cvd_risk_10y)
            for note in (rec.condition, rec.quote):
                if note:
                    lines.append("    rdfs:comment %s@en ;" % _literal(note))
            lines.append("    akg:hasGrade akg:Grade%s ." % rec.grade)
            lines.append("")

    for topic in topics:
        info = kg.topic_info.get(topic, {})
        lines.append("akgd:%s a akg:PreventiveServiceTopic ;" % topic)
        for prop, key in (("akg:aboutCondition", "condition"), ("akg:usesIntervention", "intervention")):
            if info.get(key):
                lines.append("    %s %s ;" % (prop, info[key]))
        lines.append("    rdfs:label %s@en ." % _literal(info.get("label", topic)))
        lines.append("")
        if info.get("condition"):
            lines.append("%s a biolink:Disease ; rdfs:label %s@en ." % (
                info["condition"], _literal(info.get("condition_label", info["condition"]))))
            lines.append("")
    return "\n".join(lines)


def versions_to_turtle(chains, known_at=None, view="public", prefixes=True):
    """Turtle for every label or case-definition version known by ``known_at`` in ``view``.

    The interval of a version ends only once a successor is known; the end
    may lie after ``known_at`` when the successor was announced ahead of
    taking effect. Sponsor-only notification dates are written only in the
    "sponsor" view. A trial report a label change rests on is linked with
    prov:wasInfluencedBy.
    """
    known_at = dt.date.max if known_at is None else as_date(known_at)
    lines = [PREFIXES] if prefixes else []
    if known_at != dt.date.max:
        lines.append("# Snapshot (%s view): only what was known by %s.\n" % (view, known_at.isoformat()))
    subjects = []
    for v in chains.versions:
        span = chains.interval(v.id, known_at, view)
        if span is None:
            continue
        if v.subject not in subjects:
            subjects.append(v.subject)
        start, end = span
        node = "akgd:" + v.id
        lines.append("%s a akg:%s ;" % (node, chains.kind))
        lines.append("    rdfs:label %s@en ;" % _literal(v.title))
        lines.append("    akg:versionOf akgd:%s ;" % v.subject)
        lines.append("    akg:announcedOn %s ;" % _date(v.announced.latest))
        if view == "sponsor" and v.notified is not None:
            lines.append("    akg:notifiedOn %s ;" % _date(v.notified.latest))
        lines.append("    akg:effectiveFrom %s ;" % _date(v.effective.latest))
        if v.supersedes in chains.by_id:
            lines.append("    akg:supersedes akgd:%s ;" % v.supersedes)
        for risk in v.facts.get("boxed_warning", []):
            lines.append("    akg:boxedWarningRisk %s@en ;" % _literal(risk))
        if "boxed_warning" in v.facts and not v.facts["boxed_warning"]:
            lines.append("    a akg:LabelVersionWithoutBoxedWarning ;")
        if v.facts.get("position_statement"):
            lines.append("    akg:positionStatement %s ;" % _literal(v.facts["position_statement"]))
        if v.facts.get("evidence_pmid"):
            lines.append("    prov:wasInfluencedBy pubmed:%s ;" % v.facts["evidence_pmid"])
        for url in v.sources:
            lines.append("    prov:wasDerivedFrom %s ;" % _iri(url))
        lines.append("    akg:inForceDuring %s-interval ." % node)
        lines.append("")
        _interval(lines, node, start, end)

    for subject in subjects:
        info = chains.subject_info.get(subject, {})
        lines.append("akgd:%s a akg:VersionedSubject ;" % subject)
        if info.get("rxcui"):
            lines.append("    akg:aboutDrug RXNORM:%s ;" % info["rxcui"])
        if info.get("condition"):
            lines.append("    akg:aboutCondition %s ;" % info["condition"])
        lines.append("    rdfs:label %s@en ." % _literal(info.get("label", subject)))
        lines.append("")
        if info.get("rxcui"):
            lines.append("RXNORM:%s a biolink:Drug ." % info["rxcui"])
            lines.append("")
        if info.get("condition"):
            lines.append("%s a biolink:Disease ." % info["condition"])
            lines.append("")
    return "\n".join(lines)
