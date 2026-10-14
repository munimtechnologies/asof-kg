"""Write the graph as Turtle, as it could be known on a given day."""

import datetime as dt

from .instants import as_date

PREFIXES = """@prefix akg: <https://github.com/munimv2/asof-kg/ontology#> .
@prefix akgd: <https://github.com/munimv2/asof-kg/data#> .
@prefix biolink: <https://w3id.org/biolink/vocab/> .
@prefix MESH: <http://id.nlm.nih.gov/mesh/> .
@prefix obo: <http://purl.obolibrary.org/obo/> .
@prefix prov: <http://www.w3.org/ns/prov#> .
@prefix pubmed: <https://pubmed.ncbi.nlm.nih.gov/> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix time: <http://www.w3.org/2006/time#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
"""

SEX = {"female": "obo:PATO_0000383", "male": "obo:PATO_0000384"}


def _literal(text):
    return '"%s"' % text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def _date(day):
    return '"%s"^^xsd:date' % day.isoformat()


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
        lines.append("%s-interval a time:ProperInterval ;" % node)
        if end is None:
            lines.append("    time:hasBeginning [ a time:Instant ; time:inXSDDate %s ] ." % _date(start))
        else:
            lines.append("    time:hasBeginning [ a time:Instant ; time:inXSDDate %s ] ;" % _date(start))
            lines.append("    time:hasEnd [ a time:Instant ; time:inXSDDate %s ] ." % _date(end))
        lines.append("")
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
