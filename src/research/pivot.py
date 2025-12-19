"""
Pivot exploration for Academic Research entity expansion.

Implements §3.1.1 pivot exploration patterns:
- Organization → subsidiaries, officers, location, domain
- Domain → subdomain, certificate SAN, organization
- Person → aliases, handles, affiliations

This module generates pivot queries for Cursor AI to use when designing
subqueries. It does NOT execute searches - that remains Cursor AI's decision.
"""

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, TypedDict

from src.utils.logging import get_logger


class PivotTemplateInfo(TypedDict):
    """Type definition for pivot template information."""

    templates: list[str]
    priority: str
    target_type: "EntityType | None"
    rationale: str
    operators: list[str]


logger = get_logger(__name__)


class EntityType(Enum):
    """Types of entities for pivot exploration."""

    ORGANIZATION = "organization"
    DOMAIN = "domain"
    PERSON = "person"
    LOCATION = "location"
    PRODUCT = "product"
    EVENT = "event"


class PivotType(Enum):
    """Types of pivot expansions."""

    # Organization pivots
    ORG_SUBSIDIARY = "org_subsidiary"
    ORG_OFFICER = "org_officer"
    ORG_LOCATION = "org_location"
    ORG_DOMAIN = "org_domain"
    ORG_REGISTRATION = "org_registration"
    ORG_FINANCIAL = "org_financial"

    # Domain pivots
    DOMAIN_SUBDOMAIN = "domain_subdomain"
    DOMAIN_CERTIFICATE = "domain_certificate"
    DOMAIN_WHOIS = "domain_whois"
    DOMAIN_ORGANIZATION = "domain_organization"
    DOMAIN_DNS = "domain_dns"

    # Person pivots
    PERSON_ALIAS = "person_alias"
    PERSON_HANDLE = "person_handle"
    PERSON_AFFILIATION = "person_affiliation"
    PERSON_PUBLICATION = "person_publication"

    # Cross-entity pivots
    CITATION_SOURCE = "citation_source"
    RELATED_ENTITY = "related_entity"


@dataclass
class PivotSuggestion:
    """A suggested pivot query for exploration.

    Attributes:
        pivot_type: Type of pivot expansion.
        query_template: Query template with placeholders.
        query_examples: Example queries with filled placeholders.
        source_entity: The entity being expanded.
        target_entity_type: Expected type of discovered entities.
        priority: Suggested priority (high/medium/low).
        rationale: Why this pivot is suggested.
        operators: Recommended search operators.
    """

    pivot_type: PivotType
    query_template: str
    query_examples: list[str] = field(default_factory=list)
    source_entity: str = ""
    target_entity_type: EntityType | None = None
    priority: str = "medium"
    rationale: str = ""
    operators: list[str] = field(default_factory=list)


# Organization pivot templates
ORG_PIVOT_TEMPLATES: dict[PivotType, PivotTemplateInfo] = {
    PivotType.ORG_SUBSIDIARY: {
        "templates": [
            '"{entity}" 子会社',
            '"{entity}" subsidiary',
            '"{entity}" グループ会社',
            '"{entity}" 関連会社',
            'site:edinet-fsa.go.jp "{entity}" 子会社',
        ],
        "priority": "high",
        "target_type": EntityType.ORGANIZATION,
        "rationale": "子会社・グループ会社の特定はAcademic Researchの基本",
        "operators": ["site:edinet-fsa.go.jp", "filetype:pdf"],
    },
    PivotType.ORG_OFFICER: {
        "templates": [
            '"{entity}" 代表取締役',
            '"{entity}" 役員',
            '"{entity}" CEO',
            '"{entity}" 取締役 OR 監査役',
            'site:edinet-fsa.go.jp "{entity}" 役員',
        ],
        "priority": "high",
        "target_type": EntityType.PERSON,
        "rationale": "役員情報は企業の意思決定構造を明らかにする",
        "operators": ["site:edinet-fsa.go.jp", "有価証券報告書"],
    },
    PivotType.ORG_LOCATION: {
        "templates": [
            '"{entity}" 本社 所在地',
            '"{entity}" 住所',
            '"{entity}" headquarters location',
            '"{entity}" 拠点',
        ],
        "priority": "medium",
        "target_type": EntityType.LOCATION,
        "rationale": "所在地は企業の活動範囲を示す",
        "operators": [],
    },
    PivotType.ORG_DOMAIN: {
        "templates": [
            '"{entity}" 公式サイト',
            '"{entity}" official website',
            '"{entity}" ドメイン',
        ],
        "priority": "medium",
        "target_type": EntityType.DOMAIN,
        "rationale": "公式ドメインの特定は一次資料へのアクセスに必須",
        "operators": [],
    },
    PivotType.ORG_REGISTRATION: {
        "templates": [
            '"{entity}" 法人番号',
            '"{entity}" 登記',
            'site:houjin-bangou.nta.go.jp "{entity}"',
            '"{entity}" 設立 登記簿',
        ],
        "priority": "high",
        "target_type": None,
        "rationale": "法人登記情報は一次資料として信頼性が高い",
        "operators": ["site:houjin-bangou.nta.go.jp", "site:go.jp"],
    },
    PivotType.ORG_FINANCIAL: {
        "templates": [
            '"{entity}" IR 決算',
            '"{entity}" 有価証券報告書',
            'site:edinet-fsa.go.jp "{entity}"',
            '"{entity}" 財務諸表',
        ],
        "priority": "medium",
        "target_type": None,
        "rationale": "財務情報は企業の実態把握に有用",
        "operators": ["site:edinet-fsa.go.jp", "filetype:pdf"],
    },
}


# Domain pivot templates
DOMAIN_PIVOT_TEMPLATES: dict[PivotType, PivotTemplateInfo] = {
    PivotType.DOMAIN_SUBDOMAIN: {
        "templates": [
            "site:{entity}",
            "*.{entity}",
            "inurl:{entity}",
        ],
        "priority": "medium",
        "target_type": EntityType.DOMAIN,
        "rationale": "サブドメインは組織の構造やサービスを明らかにする",
        "operators": ["site:"],
    },
    PivotType.DOMAIN_CERTIFICATE: {
        "templates": [
            'site:crt.sh "{entity}"',
            '"{entity}" certificate transparency',
            '"{entity}" SSL証明書',
        ],
        "priority": "high",
        "target_type": EntityType.DOMAIN,
        "rationale": "証明書透明性ログから関連ドメインを発見できる",
        "operators": ["site:crt.sh"],
    },
    PivotType.DOMAIN_WHOIS: {
        "templates": [
            '"{entity}" whois',
            '"{entity}" ドメイン登録者',
            '"{entity}" registrant',
        ],
        "priority": "medium",
        "target_type": EntityType.ORGANIZATION,
        "rationale": "WHOIS情報から登録者組織を特定できる",
        "operators": [],
    },
    PivotType.DOMAIN_ORGANIZATION: {
        "templates": [
            '"{entity}" 運営会社',
            '"{entity}" 運営元',
            '"{entity}" 会社概要',
        ],
        "priority": "high",
        "target_type": EntityType.ORGANIZATION,
        "rationale": "ドメインから運営組織を特定する",
        "operators": [],
    },
    PivotType.DOMAIN_DNS: {
        "templates": [
            '"{entity}" DNS レコード',
            '"{entity}" nameserver',
            '"{entity}" MX レコード',
        ],
        "priority": "low",
        "target_type": EntityType.DOMAIN,
        "rationale": "DNS情報からインフラ構成を把握できる",
        "operators": [],
    },
}


# Person pivot templates
PERSON_PIVOT_TEMPLATES: dict[PivotType, PivotTemplateInfo] = {
    PivotType.PERSON_ALIAS: {
        "templates": [
            '"{entity}" 本名',
            '"{entity}" 別名',
            '"{entity}" aka',
            '"{entity}" formerly known as',
        ],
        "priority": "medium",
        "target_type": EntityType.PERSON,
        "rationale": "別名・旧名の特定は網羅的な情報収集に必要",
        "operators": [],
    },
    PivotType.PERSON_HANDLE: {
        "templates": [
            '"{entity}" Twitter',
            '"{entity}" GitHub',
            '"{entity}" LinkedIn',
            '"{entity}" SNS アカウント',
        ],
        "priority": "low",
        "target_type": EntityType.PERSON,
        "rationale": "ソーシャルアカウントの特定（原則スキップまたは手動モード）",
        "operators": [],
    },
    PivotType.PERSON_AFFILIATION: {
        "templates": [
            '"{entity}" 所属',
            '"{entity}" 勤務先',
            '"{entity}" 経歴',
            '"{entity}" 役職',
        ],
        "priority": "high",
        "target_type": EntityType.ORGANIZATION,
        "rationale": "所属組織の特定は人物の活動範囲を明らかにする",
        "operators": [],
    },
    PivotType.PERSON_PUBLICATION: {
        "templates": [
            '"{entity}" 論文',
            '"{entity}" 著書',
            'author:"{entity}"',
            'site:researchgate.net "{entity}"',
            'site:scholar.google.com "{entity}"',
        ],
        "priority": "medium",
        "target_type": None,
        "rationale": "出版物・論文は専門性と活動履歴を示す",
        "operators": ["site:researchgate.net", "site:jstage.jst.go.jp"],
    },
}


class PivotExpander:
    """
    Generates pivot queries for Academic Research entity expansion.

    Implements §3.1.1 pivot exploration patterns. This class generates
    query suggestions for Cursor AI to consider when designing subqueries.
    It does NOT decide which pivots to execute - that remains Cursor AI's
    responsibility per §2.1 responsibility matrix.
    """

    def __init__(self) -> None:
        """Initialize the pivot expander."""
        self._org_templates = ORG_PIVOT_TEMPLATES
        self._domain_templates = DOMAIN_PIVOT_TEMPLATES
        self._person_templates = PERSON_PIVOT_TEMPLATES

    def expand_entity(
        self,
        entity_text: str,
        entity_type: EntityType | str,
        context: str = "",
        include_low_priority: bool = False,
    ) -> list[PivotSuggestion]:
        """
        Generate pivot suggestions for an entity.

        Args:
            entity_text: The entity text to expand.
            entity_type: Type of entity (organization, domain, person, etc.).
            context: Additional context about the entity.
            include_low_priority: Whether to include low-priority pivots.

        Returns:
            List of pivot suggestions ordered by priority.
        """
        if isinstance(entity_type, str):
            try:
                entity_type = EntityType(entity_type.lower())
            except ValueError:
                logger.warning(f"Unknown entity type: {entity_type}")
                return []

        suggestions = []

        if entity_type == EntityType.ORGANIZATION:
            suggestions = self._expand_organization(entity_text, context)
        elif entity_type == EntityType.DOMAIN:
            suggestions = self._expand_domain(entity_text, context)
        elif entity_type == EntityType.PERSON:
            suggestions = self._expand_person(entity_text, context)
        else:
            # For other types, try to infer applicable pivots
            suggestions = self._expand_generic(entity_text, entity_type, context)

        # Filter by priority if requested
        if not include_low_priority:
            suggestions = [s for s in suggestions if s.priority != "low"]

        # Sort by priority (high > medium > low)
        priority_order = {"high": 0, "medium": 1, "low": 2}
        suggestions.sort(key=lambda x: priority_order.get(x.priority, 1))

        return suggestions

    def _expand_organization(
        self,
        entity: str,
        context: str,
    ) -> list[PivotSuggestion]:
        """Generate pivot suggestions for an organization entity."""
        suggestions = []

        for pivot_type, template_info in self._org_templates.items():
            examples = []
            for template in template_info["templates"]:
                query = template.replace("{entity}", entity)
                examples.append(query)

            suggestion = PivotSuggestion(
                pivot_type=pivot_type,
                query_template=template_info["templates"][0],
                query_examples=examples,
                source_entity=entity,
                target_entity_type=template_info["target_type"],
                priority=template_info["priority"],
                rationale=template_info["rationale"],
                operators=template_info["operators"],
            )
            suggestions.append(suggestion)

        return suggestions

    def _expand_domain(
        self,
        entity: str,
        context: str,
    ) -> list[PivotSuggestion]:
        """Generate pivot suggestions for a domain entity."""
        suggestions = []

        # Normalize domain (remove protocol if present)
        domain = entity.lower()
        if "://" in domain:
            domain = domain.split("://")[1]
        domain = domain.rstrip("/")

        for pivot_type, template_info in self._domain_templates.items():
            examples = []
            for template in template_info["templates"]:
                query = template.replace("{entity}", domain)
                examples.append(query)

            suggestion = PivotSuggestion(
                pivot_type=pivot_type,
                query_template=template_info["templates"][0],
                query_examples=examples,
                source_entity=domain,
                target_entity_type=template_info["target_type"],
                priority=template_info["priority"],
                rationale=template_info["rationale"],
                operators=template_info["operators"],
            )
            suggestions.append(suggestion)

        return suggestions

    def _expand_person(
        self,
        entity: str,
        context: str,
    ) -> list[PivotSuggestion]:
        """Generate pivot suggestions for a person entity."""
        suggestions = []

        for pivot_type, template_info in self._person_templates.items():
            examples = []
            for template in template_info["templates"]:
                query = template.replace("{entity}", entity)
                examples.append(query)

            suggestion = PivotSuggestion(
                pivot_type=pivot_type,
                query_template=template_info["templates"][0],
                query_examples=examples,
                source_entity=entity,
                target_entity_type=template_info["target_type"],
                priority=template_info["priority"],
                rationale=template_info["rationale"],
                operators=template_info["operators"],
            )
            suggestions.append(suggestion)

        return suggestions

    def _expand_generic(
        self,
        entity: str,
        entity_type: EntityType,
        context: str,
    ) -> list[PivotSuggestion]:
        """Generate generic pivot suggestions for other entity types."""
        suggestions = []

        # Related entity search
        suggestions.append(
            PivotSuggestion(
                pivot_type=PivotType.RELATED_ENTITY,
                query_template='"{entity}" 関連',
                query_examples=[
                    f'"{entity}" 関連',
                    f'"{entity}" related',
                ],
                source_entity=entity,
                target_entity_type=None,
                priority="medium",
                rationale="関連エンティティの探索",
                operators=[],
            )
        )

        return suggestions

    def expand_all_entities(
        self,
        entities: list[dict[str, Any]],
        include_low_priority: bool = False,
    ) -> dict[str, list[PivotSuggestion]]:
        """
        Generate pivot suggestions for multiple entities.

        Args:
            entities: List of entity dictionaries with 'text' and 'type' keys.
            include_low_priority: Whether to include low-priority pivots.

        Returns:
            Dictionary mapping entity text to list of suggestions.
        """
        results = {}

        for entity_info in entities:
            entity_text = entity_info.get("text", "")
            entity_type = entity_info.get("type", "")
            context = entity_info.get("context", "")

            if entity_text:
                suggestions = self.expand_entity(
                    entity_text,
                    entity_type,
                    context,
                    include_low_priority,
                )
                if suggestions:
                    results[entity_text] = suggestions

        return results

    def get_priority_pivots(
        self,
        entities: list[dict[str, Any]],
        max_per_entity: int = 3,
    ) -> list[PivotSuggestion]:
        """
        Get highest priority pivots across all entities.

        Args:
            entities: List of entity dictionaries.
            max_per_entity: Maximum pivots per entity.

        Returns:
            List of top priority pivot suggestions.
        """
        all_pivots = []

        for entity_info in entities:
            entity_text = entity_info.get("text", "")
            entity_type = entity_info.get("type", "")
            context = entity_info.get("context", "")

            if entity_text:
                suggestions = self.expand_entity(
                    entity_text,
                    entity_type,
                    context,
                    include_low_priority=False,
                )
                # Take top N per entity
                all_pivots.extend(suggestions[:max_per_entity])

        # Sort all by priority
        priority_order = {"high": 0, "medium": 1, "low": 2}
        all_pivots.sort(key=lambda x: priority_order.get(x.priority, 1))

        return all_pivots


def detect_entity_type(text: str) -> EntityType | None:
    """
    Attempt to detect the type of an entity from its text.

    Detection order is important - more specific patterns first:
    1. Organization (has distinctive suffixes)
    2. Domain (has distinctive TLD patterns)
    3. Location (check before person to avoid false positives)
    4. Person (most general pattern)

    Args:
        text: Entity text to analyze.

    Returns:
        Detected EntityType or None if unknown.
    """
    text_lower = text.lower()

    # Organization patterns (check first - most distinctive)
    org_patterns = [
        r"株式会社",
        r"有限会社",
        r"合同会社",
        r"Inc\.?$",
        r"Corp\.?$",
        r"Ltd\.?$",
        r"LLC$",
        r"Co\.?$",
        r"Foundation$",
        r"Association$",
    ]
    for pattern in org_patterns:
        if re.search(pattern, text, re.IGNORECASE):
            return EntityType.ORGANIZATION

    # Domain patterns
    domain_patterns = [
        r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\.[a-z]{2,})+$",
        r"\.com$",
        r"\.org$",
        r"\.jp$",
        r"\.co\.jp$",
    ]
    for pattern in domain_patterns:
        if re.search(pattern, text_lower):
            return EntityType.DOMAIN

    # Location patterns (check BEFORE person - 都/県/市 are distinctive)
    location_patterns = [
        r"(都|道|府|県|市|区|町|村)$",  # Japanese administrative units
        r"(東京|大阪|名古屋|福岡|札幌|横浜|神戸|京都)",
        r"(Prefecture|City|State|Province)$",
    ]
    for pattern in location_patterns:
        if re.search(pattern, text, re.IGNORECASE):
            return EntityType.LOCATION

    # Person patterns (Japanese names, titles) - check last
    person_patterns = [
        r"(氏|さん|様)$",  # Honorifics
        r"^(Dr\.|Prof\.|Mr\.|Ms\.|Mrs\.)",  # Titles
        # Japanese name pattern - but only if not matching other patterns
        r"^[ぁ-んァ-ン一-龯]{2,4}\s*[ぁ-んァ-ン一-龯]{2,4}$",
    ]
    for pattern in person_patterns:
        if re.search(pattern, text):
            return EntityType.PERSON

    return None


def get_pivot_expander() -> PivotExpander:
    """Get a PivotExpander instance."""
    return PivotExpander()
