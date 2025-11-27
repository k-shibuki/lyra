"""
Entity Integration for Lancet.

Integrates RDAP/WHOIS and Certificate Transparency data with Entity KB.
Implements §3.1.2:
- Automatic entity extraction from registry data
- Entity normalization and KB storage
- Relationship discovery between entities

References:
- §3.1.2: Infrastructure/Registry Direct Access - Entity KB normalization
- §3.1.1: Pivot Exploration - Entity expansion
"""

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from src.crawler.rdap_whois import WHOISRecord, RDAPClient, RegistrantInfo
from src.crawler.crt_transparency import CertSearchResult, CertificateInfo, CertTransparencyClient
from src.storage.entity_kb import (
    EntityKB,
    EntityRecord,
    EntityType,
    IdentifierType,
    SourceType,
    get_entity_kb,
)
from src.utils.logging import get_logger, CausalTrace

logger = get_logger(__name__)


# =============================================================================
# Data Classes
# =============================================================================

@dataclass
class EntityExtractionResult:
    """Result of entity extraction from registry data."""
    
    # Extracted entities
    organizations: list[EntityRecord] = field(default_factory=list)
    domains: list[EntityRecord] = field(default_factory=list)
    persons: list[EntityRecord] = field(default_factory=list)
    
    # Discovered relationships
    relationships: list[tuple[str, str, str]] = field(default_factory=list)
    # (source_entity_id, target_entity_id, relationship_type)
    
    # Source tracking
    source_type: str = ""
    source_url: str | None = None
    
    # Statistics
    entities_created: int = 0
    entities_updated: int = 0
    relationships_created: int = 0
    
    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "organizations": [e.to_dict() for e in self.organizations],
            "domains": [e.to_dict() for e in self.domains],
            "persons": [e.to_dict() for e in self.persons],
            "relationships": [
                {"source": s, "target": t, "type": r}
                for s, t, r in self.relationships
            ],
            "source_type": self.source_type,
            "source_url": self.source_url,
            "entities_created": self.entities_created,
            "entities_updated": self.entities_updated,
            "relationships_created": self.relationships_created,
        }


# =============================================================================
# Entity Extractor
# =============================================================================

class EntityExtractor:
    """Extracts and normalizes entities from registry data."""
    
    def __init__(self, entity_kb: EntityKB):
        """Initialize extractor.
        
        Args:
            entity_kb: Entity KB instance for storage.
        """
        self._kb = entity_kb
    
    async def extract_from_whois(
        self,
        record: WHOISRecord,
        trace: CausalTrace | None = None,
    ) -> EntityExtractionResult:
        """Extract entities from WHOIS record.
        
        Args:
            record: WHOISRecord from RDAP/WHOIS lookup.
            trace: Causal trace for logging.
            
        Returns:
            EntityExtractionResult with extracted entities.
        """
        result = EntityExtractionResult(
            source_type="whois",
            source_url=record.source_url,
        )
        
        # 1. Create domain entity
        domain_entity = await self._kb.add_entity(
            name=record.domain,
            entity_type=EntityType.DOMAIN,
            source_type=SourceType.WHOIS,
            source_url=record.source_url,
            confidence=0.9,
            identifiers=[(IdentifierType.DOMAIN, record.domain)],
            extra_data={
                "registrar": record.registrar,
                "created_date": record.created_date.isoformat() if record.created_date else None,
                "expiry_date": record.expiry_date.isoformat() if record.expiry_date else None,
                "dnssec": record.dnssec,
                "status": record.status,
            },
        )
        result.domains.append(domain_entity)
        result.entities_created += 1
        
        # 2. Extract registrant organization
        if record.registrant:
            org_entity = await self._extract_registrant(
                record.registrant,
                record.source_url,
            )
            if org_entity:
                result.organizations.append(org_entity)
                result.entities_created += 1
                
                # Create relationship: domain -> registrant
                rel_id = await self._kb.add_relationship(
                    domain_entity.id,
                    org_entity.id,
                    "registered_by",
                    confidence=0.9,
                    source_type=SourceType.WHOIS,
                    evidence={"source_url": record.source_url},
                )
                result.relationships.append((domain_entity.id, org_entity.id, "registered_by"))
                result.relationships_created += 1
        
        # 3. Extract nameservers as domain entities
        for ns in record.nameservers:
            ns_entity = await self._kb.add_entity(
                name=ns.hostname,
                entity_type=EntityType.DOMAIN,
                source_type=SourceType.WHOIS,
                source_url=record.source_url,
                confidence=0.8,
                identifiers=[(IdentifierType.NAMESERVER, ns.hostname)],
            )
            result.domains.append(ns_entity)
            
            # Create relationship: domain -> nameserver
            await self._kb.add_relationship(
                domain_entity.id,
                ns_entity.id,
                "uses_nameserver",
                confidence=0.9,
                source_type=SourceType.WHOIS,
            )
            result.relationships.append((domain_entity.id, ns_entity.id, "uses_nameserver"))
            result.relationships_created += 1
        
        logger.info(
            f"Extracted {result.entities_created} entities from WHOIS for {record.domain}"
        )
        return result
    
    async def extract_from_cert(
        self,
        cert_result: CertSearchResult,
        trace: CausalTrace | None = None,
    ) -> EntityExtractionResult:
        """Extract entities from certificate transparency search.
        
        Args:
            cert_result: CertSearchResult from CT search.
            trace: Causal trace for logging.
            
        Returns:
            EntityExtractionResult with extracted entities.
        """
        result = EntityExtractionResult(
            source_type="cert_transparency",
            source_url=cert_result.source_url,
        )
        
        # 1. Create domain entity for queried domain
        main_domain_entity = await self._kb.add_entity(
            name=cert_result.query_domain,
            entity_type=EntityType.DOMAIN,
            source_type=SourceType.CERT_TRANSPARENCY,
            source_url=cert_result.source_url,
            confidence=0.9,
            identifiers=[(IdentifierType.DOMAIN, cert_result.query_domain)],
            extra_data={
                "earliest_cert": cert_result.earliest_cert.isoformat() if cert_result.earliest_cert else None,
                "latest_cert": cert_result.latest_cert.isoformat() if cert_result.latest_cert else None,
                "cert_count": len(cert_result.certificates),
            },
        )
        result.domains.append(main_domain_entity)
        result.entities_created += 1
        
        # 2. Extract issuer organizations
        seen_issuers = set()
        for issuer in cert_result.discovered_issuers:
            if issuer in seen_issuers:
                continue
            seen_issuers.add(issuer)
            
            issuer_entity = await self._kb.add_entity(
                name=issuer,
                entity_type=EntityType.ORGANIZATION,
                source_type=SourceType.CERT_TRANSPARENCY,
                source_url=cert_result.source_url,
                confidence=0.8,
                extra_data={"role": "certificate_issuer"},
            )
            result.organizations.append(issuer_entity)
            result.entities_created += 1
            
            # Create relationship: domain -> issuer
            await self._kb.add_relationship(
                main_domain_entity.id,
                issuer_entity.id,
                "certificate_issued_by",
                confidence=0.8,
                source_type=SourceType.CERT_TRANSPARENCY,
            )
            result.relationships.append((main_domain_entity.id, issuer_entity.id, "certificate_issued_by"))
            result.relationships_created += 1
        
        # 3. Extract related domains from SANs
        seen_domains = {cert_result.query_domain}
        for domain in cert_result.discovered_domains[:20]:  # Limit to prevent explosion
            if domain in seen_domains:
                continue
            seen_domains.add(domain)
            
            related_domain_entity = await self._kb.add_entity(
                name=domain,
                entity_type=EntityType.DOMAIN,
                source_type=SourceType.CERT_TRANSPARENCY,
                source_url=cert_result.source_url,
                confidence=0.7,
                identifiers=[(IdentifierType.DOMAIN, domain)],
            )
            result.domains.append(related_domain_entity)
            result.entities_created += 1
            
            # Create relationship: main domain -> related domain (certificate sharing)
            await self._kb.add_relationship(
                main_domain_entity.id,
                related_domain_entity.id,
                "shares_certificate",
                confidence=0.7,
                source_type=SourceType.CERT_TRANSPARENCY,
            )
            result.relationships.append((main_domain_entity.id, related_domain_entity.id, "shares_certificate"))
            result.relationships_created += 1
        
        # 4. Extract certificate entities
        for cert in cert_result.certificates[:10]:  # Limit to most recent
            cert_entity = await self._extract_certificate(cert, cert_result.source_url)
            if cert_entity:
                # Link certificate to domain
                await self._kb.add_relationship(
                    main_domain_entity.id,
                    cert_entity.id,
                    "has_certificate",
                    confidence=0.9,
                    source_type=SourceType.CERT_TRANSPARENCY,
                )
                result.relationships.append((main_domain_entity.id, cert_entity.id, "has_certificate"))
                result.relationships_created += 1
        
        logger.info(
            f"Extracted {result.entities_created} entities from CT for {cert_result.query_domain}"
        )
        return result
    
    async def _extract_registrant(
        self,
        registrant: RegistrantInfo,
        source_url: str | None,
    ) -> EntityRecord | None:
        """Extract registrant as organization entity.
        
        Args:
            registrant: RegistrantInfo from WHOIS.
            source_url: Source URL.
            
        Returns:
            EntityRecord or None if no valid data.
        """
        # Prefer organization name, fall back to registrant name
        name = registrant.organization or registrant.name
        if not name:
            return None
        
        # Build address string
        address_parts = []
        if registrant.address:
            address_parts.append(registrant.address)
        if registrant.city:
            address_parts.append(registrant.city)
        if registrant.state:
            address_parts.append(registrant.state)
        if registrant.country:
            address_parts.append(registrant.country)
        
        address = ", ".join(address_parts) if address_parts else None
        
        # Build identifiers
        identifiers = []
        if registrant.email:
            identifiers.append((IdentifierType.EMAIL, registrant.email))
        if registrant.phone:
            identifiers.append((IdentifierType.PHONE, registrant.phone))
        
        return await self._kb.add_entity(
            name=name,
            entity_type=EntityType.ORGANIZATION,
            address=address,
            country=registrant.country,
            source_type=SourceType.WHOIS,
            source_url=source_url,
            confidence=0.8,
            identifiers=identifiers if identifiers else None,
            extra_data={
                "registrant_name": registrant.name,
                "registrant_org": registrant.organization,
            },
        )
    
    async def _extract_certificate(
        self,
        cert: CertificateInfo,
        source_url: str | None,
    ) -> EntityRecord | None:
        """Extract certificate as entity.
        
        Args:
            cert: CertificateInfo from CT.
            source_url: Source URL.
            
        Returns:
            EntityRecord or None.
        """
        return await self._kb.add_entity(
            name=f"Certificate {cert.cert_id}",
            entity_type=EntityType.CERTIFICATE,
            source_type=SourceType.CERT_TRANSPARENCY,
            source_url=cert.source_url or source_url,
            confidence=0.9,
            identifiers=[(IdentifierType.CERTIFICATE_ID, cert.cert_id)],
            extra_data={
                "common_name": cert.common_name,
                "issuer_name": cert.issuer_name,
                "issuer_org": cert.issuer_org,
                "not_before": cert.not_before.isoformat() if cert.not_before else None,
                "not_after": cert.not_after.isoformat() if cert.not_after else None,
                "san_dns": cert.san_dns,
                "is_wildcard": cert.is_wildcard,
            },
        )


# =============================================================================
# Integration Manager
# =============================================================================

class RegistryEntityIntegration:
    """Manages integration between registry data and Entity KB.
    
    Provides high-level methods for extracting entities from
    RDAP/WHOIS and Certificate Transparency data.
    """
    
    def __init__(
        self,
        entity_kb: EntityKB,
        rdap_client: RDAPClient | None = None,
        ct_client: CertTransparencyClient | None = None,
    ):
        """Initialize integration manager.
        
        Args:
            entity_kb: Entity KB instance.
            rdap_client: Optional RDAP client.
            ct_client: Optional CT client.
        """
        self._kb = entity_kb
        self._rdap_client = rdap_client
        self._ct_client = ct_client
        self._extractor = EntityExtractor(entity_kb)
    
    async def process_domain(
        self,
        domain: str,
        include_whois: bool = True,
        include_ct: bool = True,
        trace: CausalTrace | None = None,
    ) -> EntityExtractionResult:
        """Process a domain and extract all related entities.
        
        Args:
            domain: Domain to process.
            include_whois: Whether to include WHOIS data.
            include_ct: Whether to include CT data.
            trace: Causal trace.
            
        Returns:
            Combined EntityExtractionResult.
        """
        result = EntityExtractionResult()
        
        # Process WHOIS
        if include_whois and self._rdap_client:
            whois_record = await self._rdap_client.lookup(domain, trace=trace)
            if whois_record:
                whois_result = await self._extractor.extract_from_whois(whois_record, trace)
                self._merge_results(result, whois_result)
        
        # Process CT
        if include_ct and self._ct_client:
            ct_result = await self._ct_client.search(domain, trace=trace)
            if ct_result:
                ct_extraction = await self._extractor.extract_from_cert(ct_result, trace)
                self._merge_results(result, ct_extraction)
        
        logger.info(
            f"Processed domain {domain}: {result.entities_created} entities, "
            f"{result.relationships_created} relationships"
        )
        return result
    
    async def process_domains_batch(
        self,
        domains: list[str],
        include_whois: bool = True,
        include_ct: bool = True,
        max_concurrent: int = 2,
        trace: CausalTrace | None = None,
    ) -> dict[str, EntityExtractionResult]:
        """Process multiple domains.
        
        Args:
            domains: List of domains to process.
            include_whois: Whether to include WHOIS data.
            include_ct: Whether to include CT data.
            max_concurrent: Maximum concurrent processing.
            trace: Causal trace.
            
        Returns:
            Dictionary mapping domain to EntityExtractionResult.
        """
        results = {}
        semaphore = asyncio.Semaphore(max_concurrent)
        
        async def process_one(domain: str) -> tuple[str, EntityExtractionResult]:
            async with semaphore:
                result = await self.process_domain(
                    domain,
                    include_whois=include_whois,
                    include_ct=include_ct,
                    trace=trace,
                )
                # Rate limiting
                await asyncio.sleep(1.0)
                return (domain, result)
        
        tasks = [process_one(d) for d in domains]
        for future in asyncio.as_completed(tasks):
            domain, result = await future
            results[domain] = result
        
        return results
    
    async def get_domain_entities(
        self,
        domain: str,
    ) -> list[EntityRecord]:
        """Get all entities associated with a domain.
        
        Args:
            domain: Domain to look up.
            
        Returns:
            List of associated EntityRecord.
        """
        # Find domain entity
        matches = await self._kb.find_entity(
            name=domain,
            entity_type=EntityType.DOMAIN,
            threshold=0.9,
        )
        
        if not matches:
            return []
        
        domain_entity = matches[0].entity
        entities = [domain_entity]
        
        # Get related entities
        related = await self._kb.get_related_entities(domain_entity.id)
        for entity, rel_type, confidence in related:
            entities.append(entity)
        
        return entities
    
    async def discover_related_organizations(
        self,
        domain: str,
    ) -> list[tuple[EntityRecord, str, float]]:
        """Discover organizations related to a domain.
        
        Args:
            domain: Domain to analyze.
            
        Returns:
            List of (organization, relationship_type, confidence) tuples.
        """
        # Find domain entity
        matches = await self._kb.find_entity(
            name=domain,
            entity_type=EntityType.DOMAIN,
            threshold=0.9,
        )
        
        if not matches:
            return []
        
        domain_entity = matches[0].entity
        
        # Get related organizations
        related = await self._kb.get_related_entities(domain_entity.id)
        
        orgs = []
        for entity, rel_type, confidence in related:
            if entity.entity_type == EntityType.ORGANIZATION:
                orgs.append((entity, rel_type, confidence))
        
        return orgs
    
    def _merge_results(
        self,
        target: EntityExtractionResult,
        source: EntityExtractionResult,
    ) -> None:
        """Merge source result into target.
        
        Args:
            target: Target result to update.
            source: Source result to merge from.
        """
        target.organizations.extend(source.organizations)
        target.domains.extend(source.domains)
        target.persons.extend(source.persons)
        target.relationships.extend(source.relationships)
        target.entities_created += source.entities_created
        target.entities_updated += source.entities_updated
        target.relationships_created += source.relationships_created


# =============================================================================
# Factory Functions
# =============================================================================

async def get_registry_entity_integration(
    db: Any = None,
    fetcher: Any = None,
) -> RegistryEntityIntegration:
    """Get RegistryEntityIntegration instance.
    
    Args:
        db: Database instance.
        fetcher: URL fetcher for RDAP/CT clients.
        
    Returns:
        Configured RegistryEntityIntegration.
    """
    from src.crawler.rdap_whois import get_rdap_client
    from src.crawler.crt_transparency import get_cert_transparency_client
    
    entity_kb = await get_entity_kb(db)
    rdap_client = get_rdap_client(fetcher) if fetcher else None
    ct_client = get_cert_transparency_client(fetcher) if fetcher else None
    
    return RegistryEntityIntegration(
        entity_kb=entity_kb,
        rdap_client=rdap_client,
        ct_client=ct_client,
    )

