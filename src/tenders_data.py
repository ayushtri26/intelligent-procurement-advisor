"""Seed tender definitions and shared constants for the tender workspace.

These are the three preloaded example tenders — the starting contents of
the tender repository (src/tender_repository.py), not a hardcoded universe
of "the only three tenders that can ever exist". User-created tenders
(src/tender_form.py) live alongside these in the repository and are
functionally identical once created.

Nothing here computes a score — src/recommendation_engine.py does that from
these requirements plus the already-scored vendor dataframe.
"""
from __future__ import annotations

PROCUREMENT_TYPES = ["Goods", "Services", "Works", "IT / Technology", "Logistics", "Professional Services", "Other"]

CURRENCIES = ["INR", "USD", "EUR", "GBP"]

TENDER_STATUSES = ["Draft", "Open", "Under Evaluation", "Awaiting Approval", "Awarded", "Closed"]

DEFAULT_EVALUATION_CRITERIA = {
    "technical_compliance": 0.25,
    "price": 0.25,
    "delivery": 0.20,
    "past_performance": 0.15,
    "warranty": 0.10,
    "risk": 0.05,
}

EVALUATION_CRITERIA_LABELS = {
    "technical_compliance": "Technical Compliance",
    "price": "Price",
    "delivery": "Delivery",
    "past_performance": "Past Performance",
    "warranty": "Warranty / Service",
    "risk": "Risk",
}

SEED_TENDERS: dict[str, dict] = {
    "TND-001": {
        "tender_id": "TND-001",
        "title": "Laptop Procurement — FY26",
        "description": "Annual refresh of business laptops for the engineering and sales organizations.",
        "category": "IT Hardware",
        "vendor_category_match": ["Electronics"],
        "department": "IT Infrastructure",
        "procurement_type": "IT / Technology",
        "budget": 32000,
        "currency": "USD",
        "quantity": 500,
        "submission_deadline": "2026-09-15",
        "contract_start_date": "2026-10-01",
        "contract_duration": "3 years",
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
        "delivery_location": "Central Distribution Warehouse, Bengaluru",
        "minimum_on_time_delivery": 90,
        "warranty_requirement": "Minimum 3-year on-site warranty",
        "sla_requirement": "Next-business-day on-site support response",
        "support_requirement": "Dedicated account manager, 8x5 helpdesk",
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
        "status": "Under Evaluation",
        "source": "Seed Data",
        "created_by": "System",
        "created_at": "2026-07-01 09:00:00",
        "last_modified_at": "2026-07-01 09:00:00",
    },
    "TND-002": {
        "tender_id": "TND-002",
        "title": "Office Furniture Procurement — HQ Expansion",
        "description": "Furnishing for the new headquarters expansion floor: desks, chairs, and storage.",
        "category": "Furniture",
        "vendor_category_match": ["Furniture"],
        "department": "Facilities",
        "procurement_type": "Goods",
        "budget": 20000,
        "currency": "USD",
        "quantity": 300,
        "submission_deadline": "2026-09-30",
        "contract_start_date": "2026-11-01",
        "contract_duration": "1 year",
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
        "delivery_location": "HQ Expansion Floor, Bengaluru",
        "minimum_on_time_delivery": 85,
        "warranty_requirement": "Minimum 2-year warranty on frames and mechanisms",
        "sla_requirement": "Installation included, 2-week install window",
        "support_requirement": "On-site assembly team",
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
        "status": "Open",
        "source": "Seed Data",
        "created_by": "System",
        "created_at": "2026-07-01 09:00:00",
        "last_modified_at": "2026-07-01 09:00:00",
    },
    "TND-003": {
        "tender_id": "TND-003",
        "title": "Logistics & Freight Services — Regional Distribution",
        "description": "Regional freight and last-mile distribution services for the northern distribution hub.",
        "category": "Logistics Services",
        "vendor_category_match": ["Logistics"],
        "department": "Supply Chain",
        "procurement_type": "Logistics",
        "budget": 22500,
        "currency": "USD",
        "quantity": 1,
        "submission_deadline": "2026-09-01",
        "contract_start_date": "2026-09-15",
        "contract_duration": "2 years",
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
        "delivery_location": "Northern Regional Distribution Hub",
        "minimum_on_time_delivery": 90,
        "warranty_requirement": "Service-level agreement with damage/loss coverage",
        "sla_requirement": "99% on-time pickup, real-time tracking portal",
        "support_requirement": "24x7 dispatch coordination line",
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
        "status": "Under Evaluation",
        "source": "Seed Data",
        "created_by": "System",
        "created_at": "2026-07-01 09:00:00",
        "last_modified_at": "2026-07-01 09:00:00",
    },
}

DEFAULT_TENDER_ID = "TND-001"
