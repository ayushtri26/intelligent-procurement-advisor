"""Structured mock tender definitions — the registry the recommendation
engine (src/recommendation_engine.py) reads to determine, per tender: which
vendor category is eligible, which requirements are mandatory, and how the
evaluation criteria should be weighted.

This is demo/config data, not business logic: each tender is a plain
structured record (matching the shape a real tender-intake form or document
parser would eventually populate), not a fabricated recommendation. Nothing
here computes a score — src/recommendation_engine.py does that from these
requirements plus the already-scored vendor dataframe.
"""
from __future__ import annotations

TENDERS: dict[str, dict] = {
    "TND-001": {
        "tender_id": "TND-001",
        "title": "Laptop Procurement — FY26",
        "category": "IT Hardware",
        "vendor_category_match": ["Electronics"],
        "budget": 32000,
        "quantity": 500,
        "technical_requirements": [
            "16GB RAM minimum",
            "Intel i5 11th generation or higher / equivalent",
            "512GB SSD storage",
            "Full HD display, 14 inch or larger",
        ],
        "mandatory_requirements": [
            "Minimum 3 quality/technical certifications",
            "No more than one prior compliance violation",
            "Quality rating of at least 7.0 / 10",
        ],
        "certifications": ["ISO 9001", "Energy Star", "RoHS"],
        "delivery_requirement": "Within 45 days of purchase order",
        "warranty_requirement": "Minimum 3-year on-site warranty",
        "evaluation_criteria": {
            "technical_compliance": 0.30,
            "price": 0.25,
            "delivery": 0.15,
            "past_performance": 0.15,
            "warranty": 0.10,
            "risk": 0.05,
        },
        "min_certifications": 3,
        "min_quality_rating": 7.0,
    },
    "TND-002": {
        "tender_id": "TND-002",
        "title": "Office Furniture Procurement — HQ Expansion",
        "category": "Furniture",
        "vendor_category_match": ["Furniture"],
        "budget": 20000,
        "quantity": 300,
        "technical_requirements": [
            "Ergonomic seating meeting BIFMA standards",
            "Height-adjustable workstations",
            "Fire-retardant upholstery",
        ],
        "mandatory_requirements": [
            "Minimum 2 quality/material certifications",
            "No open compliance violations",
            "Quality rating of at least 6.5 / 10",
        ],
        "certifications": ["BIFMA", "FSC Certified Wood"],
        "delivery_requirement": "Within 60 days of purchase order",
        "warranty_requirement": "Minimum 2-year warranty on frames and mechanisms",
        "evaluation_criteria": {
            "technical_compliance": 0.20,
            "price": 0.30,
            "delivery": 0.20,
            "past_performance": 0.20,
            "warranty": 0.05,
            "risk": 0.05,
        },
        "min_certifications": 2,
        "min_quality_rating": 6.5,
    },
    "TND-003": {
        "tender_id": "TND-003",
        "title": "Logistics & Freight Services — Regional Distribution",
        "category": "Logistics Services",
        "vendor_category_match": ["Logistics"],
        "budget": 22500,
        "quantity": 1,
        "technical_requirements": [
            "Real-time shipment tracking",
            "Coverage across all regional distribution hubs",
            "Temperature-controlled transport option",
        ],
        "mandatory_requirements": [
            "Minimum 3 quality/safety certifications",
            "No more than one prior compliance violation",
            "Quality rating of at least 7.0 / 10",
        ],
        "certifications": ["ISO 9001", "C-TPAT"],
        "delivery_requirement": "On-time delivery rate of 90% or higher",
        "warranty_requirement": "Service-level agreement with damage/loss coverage",
        "evaluation_criteria": {
            "technical_compliance": 0.15,
            "price": 0.20,
            "delivery": 0.30,
            "past_performance": 0.20,
            "warranty": 0.05,
            "risk": 0.10,
        },
        "min_certifications": 3,
        "min_quality_rating": 7.0,
    },
}

DEFAULT_TENDER_ID = "TND-001"


def get_tender(tender_id: str) -> dict:
    return TENDERS.get(tender_id, TENDERS[DEFAULT_TENDER_ID])


def list_tenders() -> list[dict]:
    return list(TENDERS.values())


def tender_options() -> dict[str, str]:
    """{tender_id: display_label} for selectbox rendering."""
    return {t["tender_id"]: f"{t['title']} ({t['category']})" for t in TENDERS.values()}
