"""Builds the CandidateCapabilityGraph from the profile and the master CV."""

import json
import re
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from packages.domain.enums import CapabilityKind
from packages.domain.models import CandidateProfileModel
from packages.domain.role_discovery import (
    CandidateCapabilityGraph,
    CapabilityCluster,
    CapabilityNode,
    SeniorityAssessment,
    slugify,
)
from packages.llm.base import LLMMessage
from packages.llm.gateway import LLMGateway
from packages.role_discovery.lexicon import CAPABILITY_LEXICON

CAPABILITY_SYSTEM_PROMPT = """You are a career analyst building a semantic capability graph for one candidate.

You are given a candidate profile and their full master CV. Extract what the person can
actually DO, with the evidence for each claim. This graph is later used to infer which
professional roles they should search for, so precision matters more than breadth.

CRITICAL RULES:
1. Never invent a capability. Every node must be supported by the supplied text, and the
   evidence array must quote or closely paraphrase the supporting passage.
2. Keep the nine facets strictly separate. A tool the candidate uses is a "technology";
   what they can accomplish with it is a "capability"; the industry they applied it in is a
   "domain"; what they were accountable for is a "responsibility".
3. Clusters are the important part. A cluster is a COMBINATION of nodes that together
   imply something none of them implies alone, for example engine work plus perception plus
   hardware integration plus shipping a product. Produce 4 to 8 clusters.
4. Strength is 0.0 to 1.0 and reflects depth of evidence and recency, not enthusiasm.
5. Output MUST be valid JSON matching the schema exactly, with no prose around it.

JSON OUTPUT SCHEMA:
{
  "summary": "<3 sentence description of the candidate as a professional>",
  "seniority": {
    "level": "junior|mid|senior|staff|lead|principal|executive",
    "years_experience": <number>,
    "leads_people": <bool>,
    "owns_product": <bool>,
    "rationale": "<why>"
  },
  "nodes": [
    {
      "label": "<short name>",
      "kind": "technology|capability|domain|responsibility|seniority|leadership|product-ownership|technical-depth|transferable",
      "strength": <0.0-1.0>,
      "years": <number or null>,
      "evidence": ["<supporting passage>"]
    }
  ],
  "clusters": [
    {
      "label": "<name of the combination>",
      "nodes": ["<node label>", "<node label>", ...],
      "strength": <0.0-1.0>,
      "rationale": "<what this combination makes the candidate able to do>"
    }
  ],
  "notes": "<anything a recruiter would miss on a first read>"
}
"""

_SENIORITY_MARKERS: List[Tuple[str, str]] = [
    ("chief technology officer", "executive"),
    ("cto", "executive"),
    ("vp of engineering", "executive"),
    ("head of", "lead"),
    ("engineering manager", "lead"),
    ("team lead", "lead"),
    ("tech lead", "lead"),
    ("technical lead", "lead"),
    ("principal", "principal"),
    ("staff engineer", "staff"),
    ("senior", "senior"),
    ("junior", "junior"),
    ("intern", "junior"),
]

_LEVEL_ORDER = ["junior", "mid", "senior", "staff", "lead", "principal", "executive"]

# Strength ceilings for capabilities that the CV does not evidence.
INTEREST_STRENGTH = 0.45
ASPIRATION_STRENGTH = 0.3


def _alias_pattern(alias: str) -> re.Pattern:
    escaped = re.escape(alias.strip())
    # Aliases padded with spaces in the lexicon (" ar ") are matched literally so
    # two-letter terms do not fire inside unrelated words.
    if alias.startswith(" ") or alias.endswith(" "):
        return re.compile(escaped)
    if not alias[0].isalnum():
        return re.compile(escaped)
    return re.compile(rf"(?<![A-Za-z0-9]){escaped}(?![A-Za-z0-9+#])")


_COMPILED_ALIASES = {
    entry.label: [(alias, _alias_pattern(alias)) for alias in entry.aliases]
    for entry in CAPABILITY_LEXICON
}


class CapabilityGraphBuilder:
    """Produces a capability graph, preferring the LLM and falling back to the lexicon."""

    def __init__(self, llm_gateway: Optional[LLMGateway] = None):
        self.gateway = llm_gateway or LLMGateway.get()

    async def build(
        self,
        profile: CandidateProfileModel,
        resume_digest: str = "",
        use_llm: bool = True,
        version: int = 1,
    ) -> CandidateCapabilityGraph:
        corpus = self._corpus(profile, resume_digest)

        if use_llm:
            try:
                response = await self.gateway.generate(
                    [
                        LLMMessage(role="system", content=CAPABILITY_SYSTEM_PROMPT),
                        LLMMessage(role="user", content=corpus),
                    ],
                    temperature=0.2,
                    response_format="json",
                )
                graph = self._parse(response.content, profile, version)
                if graph is not None and len(graph.nodes) >= 5:
                    return graph
            except Exception:
                pass

        return self.heuristic_graph(profile, resume_digest, version=version)

    # -- corpus ------------------------------------------------------------

    def _corpus(self, profile: CandidateProfileModel, resume_digest: str) -> str:
        prefs = profile.job_preferences
        return f"""CANDIDATE PROFILE

Name: {profile.identity.name}
Based in: {profile.identity.location}
Websites: {profile.identity.website or "n/a"} | {profile.identity.github or "n/a"}

Stated interests: {", ".join(prefs.interests) or "none stated"}
Job titles the candidate happens to have written down (these are hints, NOT conclusions):
{", ".join(prefs.roles) or "none stated"}

Location constraints: {", ".join(prefs.locations) or "none"}
Remote: {prefs.remote} | Hybrid: {prefs.hybrid} | Onsite: {prefs.onsite} | Relocation: {prefs.relocation}
Salary expectation: minimum {prefs.minimum_salary}, preferred {prefs.preferred_salary} ({"/".join(prefs.currencies)})
Work authorisation: EU={prefs.visa_requirements.authorized_eu}, US={prefs.visa_requirements.authorized_us}
Roles the candidate has excluded: {", ".join(profile.application_preferences.excluded_roles) or "none"}

MASTER CV

{resume_digest or "(master CV unavailable — reason only from the profile above)"}
"""

    # -- LLM parsing -------------------------------------------------------

    def _parse(
        self,
        content: str,
        profile: CandidateProfileModel,
        version: int,
    ) -> Optional[CandidateCapabilityGraph]:
        parsed = json.loads(content)
        raw_nodes = parsed.get("nodes")
        if not isinstance(raw_nodes, list):
            return None

        nodes: List[CapabilityNode] = []
        by_label: Dict[str, CapabilityNode] = {}
        for raw in raw_nodes:
            if not isinstance(raw, dict):
                continue
            label = str(raw.get("label", "")).strip()
            if not label:
                continue
            try:
                kind = CapabilityKind(str(raw.get("kind", "capability")).strip().lower())
            except ValueError:
                kind = CapabilityKind.CAPABILITY
            evidence = raw.get("evidence")
            node = CapabilityNode.build(
                label,
                kind,
                strength=_clamp_float(raw.get("strength"), 0.5),
                years=_opt_float(raw.get("years")),
                evidence=[str(e) for e in evidence][:4] if isinstance(evidence, list) else [],
            )
            if node.id in {n.id for n in nodes}:
                continue
            nodes.append(node)
            by_label[label.lower()] = node

        if not nodes:
            return None

        clusters: List[CapabilityCluster] = []
        for raw in parsed.get("clusters") or []:
            if not isinstance(raw, dict):
                continue
            label = str(raw.get("label", "")).strip()
            member_labels = raw.get("nodes")
            if not label or not isinstance(member_labels, list):
                continue
            node_ids = [
                by_label[str(m).strip().lower()].id
                for m in member_labels
                if str(m).strip().lower() in by_label
            ]
            if len(node_ids) < 2:
                continue
            clusters.append(
                CapabilityCluster(
                    id=f"cluster_{slugify(label)}",
                    label=label,
                    node_ids=node_ids,
                    strength=_clamp_float(raw.get("strength"), 0.6),
                    rationale=str(raw.get("rationale", "")),
                )
            )

        raw_seniority = parsed.get("seniority") or {}
        seniority = SeniorityAssessment(
            level=str(raw_seniority.get("level", "mid")).strip().lower() or "mid",
            years_experience=_opt_float(raw_seniority.get("years_experience")),
            leads_people=bool(raw_seniority.get("leads_people", False)),
            owns_product=bool(raw_seniority.get("owns_product", False)),
            rationale=str(raw_seniority.get("rationale", "")),
        )

        return CandidateCapabilityGraph(
            version=version,
            generated_by="llm",
            summary=str(parsed.get("summary", "")),
            seniority=seniority,
            nodes=nodes,
            clusters=clusters,
            constraints=_constraints(profile),
            notes=str(parsed.get("notes", "")),
        )

    # -- deterministic fallback -------------------------------------------

    def heuristic_graph(
        self,
        profile: CandidateProfileModel,
        resume_digest: str = "",
        version: int = 1,
    ) -> CandidateCapabilityGraph:
        """Lexicon-driven graph. Used with no LLM configured or on a bad response.

        The three input texts carry very different weight. The CV is evidence. The
        candidate's stated interests show real domain affinity but prove nothing
        about depth. The job titles and seed queries they wrote down are wishes: a
        desired title of CTO must never become proof of leadership experience.
        """
        prefs = profile.job_preferences
        evidence_corpus = resume_digest.lower()
        interest_corpus = " ".join(prefs.interests).lower()
        aspiration_corpus = " ".join(
            list(prefs.roles) + list(profile.discovery.seed_queries)
        ).lower()

        nodes: List[CapabilityNode] = []
        for entry in CAPABILITY_LEXICON:
            patterns = _COMPILED_ALIASES[entry.label]

            hits = 0
            evidence: List[str] = []
            for alias, pattern in patterns:
                found = pattern.findall(evidence_corpus)
                hits += len(found)
                if found and len(evidence) < 3:
                    evidence.append(_evidence_snippet(evidence_corpus, pattern) or alias)

            if hits:
                strength = min(1.0, 0.35 + 0.12 * hits)
            elif any(pattern.search(interest_corpus) for _, pattern in patterns):
                strength = INTEREST_STRENGTH
                evidence = ["Stated as an interest; depth not evidenced in the CV."]
            elif any(pattern.search(aspiration_corpus) for _, pattern in patterns):
                strength = ASPIRATION_STRENGTH
                evidence = ["Appears only in the candidate's own target titles."]
            else:
                continue

            nodes.append(
                CapabilityNode.build(
                    entry.label,
                    entry.kind,
                    strength=round(strength, 2),
                    evidence=evidence,
                )
            )

        clusters = self._heuristic_clusters(nodes, resume_digest)
        seniority = self._heuristic_seniority(evidence_corpus, nodes)

        for node in nodes:
            cluster_peers = {
                peer
                for cluster in clusters
                if node.id in cluster.node_ids
                for peer in cluster.node_ids
                if peer != node.id
            }
            node.related = sorted(cluster_peers)[:8]

        return CandidateCapabilityGraph(
            version=version,
            generated_by="heuristic",
            summary=(
                f"{profile.identity.name} shows {len(nodes)} evidenced capabilities across "
                f"{len({n.kind for n in nodes})} facets, clustered into {len(clusters)} "
                "combinations."
            ),
            seniority=seniority,
            nodes=nodes,
            clusters=clusters,
            constraints=_constraints(profile),
            notes=(
                "Built from the capability lexicon because no usable model response "
                "was available."
            ),
        )

    def _heuristic_clusters(
        self,
        nodes: List[CapabilityNode],
        resume_digest: str,
    ) -> List[CapabilityCluster]:
        """Groups capabilities that co-occur inside the same CV entry.

        Co-occurrence in one role or project is the evidence that the candidate has
        actually combined those capabilities, rather than holding them separately.
        """
        if not nodes:
            return []

        entries = _split_cv_entries(resume_digest)
        clusters: List[CapabilityCluster] = []
        seen_signatures: set = set()

        for heading, body in entries:
            body_lower = body.lower()
            members = [
                node
                for node in nodes
                if any(
                    pattern.search(body_lower)
                    for _, pattern in _COMPILED_ALIASES.get(node.label, [])
                )
            ]
            if len(members) < 3:
                continue
            kinds = {node.kind for node in members}
            if len(kinds) < 2:
                continue
            signature = tuple(sorted(node.id for node in members))
            if signature in seen_signatures:
                continue
            seen_signatures.add(signature)
            label = heading[:80] or f"Combination {len(clusters) + 1}"
            clusters.append(
                CapabilityCluster(
                    id=f"cluster_{slugify(label)}" or f"cluster_{len(clusters)}",
                    label=label,
                    node_ids=[node.id for node in members],
                    strength=round(min(1.0, sum(n.strength for n in members) / len(members)), 2),
                    rationale=(
                        "Applied together in the same role or project: "
                        + ", ".join(node.label for node in members[:6])
                    ),
                )
            )

        if not clusters:
            # No CV text to segment: fall back to one cluster per capability facet pair.
            strongest = sorted(nodes, key=lambda n: n.strength, reverse=True)[:8]
            if len(strongest) >= 3:
                clusters.append(
                    CapabilityCluster(
                        id="cluster_core_profile",
                        label="Core profile",
                        node_ids=[node.id for node in strongest],
                        strength=round(sum(n.strength for n in strongest) / len(strongest), 2),
                        rationale="Strongest evidenced capabilities across the profile.",
                    )
                )
        return clusters[:8]

    def _heuristic_seniority(
        self,
        corpus: str,
        nodes: List[CapabilityNode],
    ) -> SeniorityAssessment:
        level = "mid"
        for marker, marker_level in _SENIORITY_MARKERS:
            if marker in corpus:
                # The marker list is ordered most senior first, so the first hit wins.
                level = marker_level
                break

        years = None
        year_match = re.search(r"(\d{1,2})\+?\s*(?:years|años|yrs)", corpus)
        if year_match:
            years = float(year_match.group(1))

        # Only CV-evidenced capabilities count here. Interests and target titles
        # sit at or below INTEREST_STRENGTH and say nothing about responsibility.
        leads = any(
            node.kind == CapabilityKind.LEADERSHIP and node.strength > INTEREST_STRENGTH
            for node in nodes
        )
        owns = any(
            node.kind == CapabilityKind.PRODUCT_OWNERSHIP and node.strength > INTEREST_STRENGTH
            for node in nodes
        )
        if leads and _LEVEL_ORDER.index(level) < _LEVEL_ORDER.index("lead"):
            level = "lead" if "led a team" in corpus or "head of" in corpus else level

        return SeniorityAssessment(
            level=level,
            years_experience=years,
            leads_people=leads,
            owns_product=owns,
            rationale=(
                "Derived from title markers and the presence of leadership and product "
                "ownership evidence in the CV."
            ),
        )


def _constraints(profile: CandidateProfileModel) -> Dict[str, object]:
    prefs = profile.job_preferences
    return {
        "locations": list(prefs.locations),
        "remote": prefs.remote,
        "hybrid": prefs.hybrid,
        "onsite": prefs.onsite,
        "relocation": prefs.relocation,
        "minimum_salary": prefs.minimum_salary,
        "preferred_salary": prefs.preferred_salary,
        "currencies": list(prefs.currencies),
        "authorized_eu": prefs.visa_requirements.authorized_eu,
        "authorized_us": prefs.visa_requirements.authorized_us,
        "excluded_roles": list(profile.application_preferences.excluded_roles),
        "excluded_companies": list(profile.application_preferences.excluded_companies),
        "generated_at": datetime.utcnow().isoformat(),
    }


def _split_cv_entries(resume_digest: str) -> List[Tuple[str, str]]:
    """Splits the digest into (heading, body) pairs, one per CV entry."""
    if not resume_digest:
        return []
    entries: List[Tuple[str, str]] = []
    current_heading = ""
    current_lines: List[str] = []
    for line in resume_digest.split("\n"):
        if line.startswith("## "):
            continue
        if line.startswith("- "):
            if current_lines:
                entries.append((current_heading, "\n".join(current_lines)))
            current_heading = line[2:].strip()
            current_lines = [current_heading]
        elif current_lines:
            current_lines.append(line.strip())
    if current_lines:
        entries.append((current_heading, "\n".join(current_lines)))
    return entries


def _evidence_snippet(corpus: str, pattern: re.Pattern) -> str:
    match = pattern.search(corpus)
    if not match:
        return ""
    start = max(0, match.start() - 60)
    end = min(len(corpus), match.end() + 60)
    return "..." + corpus[start:end].replace("\n", " ").strip() + "..."


def _clamp_float(value: object, default: float) -> float:
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default
    return max(0.0, min(1.0, number))


def _opt_float(value: object) -> Optional[float]:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
