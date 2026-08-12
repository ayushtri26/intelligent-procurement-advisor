"""Tests for the dynamic tender data store (src/tender_repository.py) — the
core of "do not hardcode only the three existing tenders"."""
import streamlit as st

from src import tender_repository
from src.tenders_data import SEED_TENDERS


def setup_function():
    st.session_state.clear()


def test_repository_seeds_from_seed_tenders():
    tender_repository.init_repository()
    ids = {t["tender_id"] for t in tender_repository.get_all_tenders()}
    assert ids == set(SEED_TENDERS.keys())


def test_generate_tender_id_is_unique_and_not_derived_from_title():
    tid1 = tender_repository.generate_tender_id()
    tender_repository.create_tender({"title": "Some Tender", "tender_id": tid1})
    tid2 = tender_repository.generate_tender_id()
    assert tid1 != tid2
    assert "Some Tender" not in tid1
    assert tid1.startswith("TND-")


def test_create_tender_adds_to_repository_and_is_selectable():
    new_id = tender_repository.create_tender({"title": "Smartphone Procurement FY27", "category": "Electronics"})
    all_ids = [t["tender_id"] for t in tender_repository.get_all_tenders()]
    assert new_id in all_ids
    options = tender_repository.tender_options()
    assert options[new_id] == "Smartphone Procurement FY27"


def test_create_tender_defaults_to_draft_status_and_user_created_source():
    new_id = tender_repository.create_tender({"title": "New Tender"})
    tender = tender_repository.get_tender(new_id)
    assert tender["status"] == "Draft"
    assert tender["source"] == "User Created"


def test_created_tender_has_a_created_at_timestamp():
    new_id = tender_repository.create_tender({"title": "New Tender"})
    tender = tender_repository.get_tender(new_id)
    assert tender["created_at"]
    assert tender["last_modified_at"]


def test_update_tender_mutates_in_place_and_bumps_last_modified():
    new_id = tender_repository.create_tender({"title": "Original Title"})
    original_modified = tender_repository.get_tender(new_id)["last_modified_at"]
    tender_repository.update_tender(new_id, {"title": "Updated Title", "budget": 5000})
    updated = tender_repository.get_tender(new_id)
    assert updated["title"] == "Updated Title"
    assert updated["budget"] == 5000
    assert updated["last_modified_at"] >= original_modified


def test_set_status_changes_only_status():
    new_id = tender_repository.create_tender({"title": "Status Test"})
    tender_repository.set_status(new_id, "Open")
    assert tender_repository.get_tender(new_id)["status"] == "Open"


def test_duplicate_tender_creates_independent_draft_copy():
    new_id = tender_repository.duplicate_tender("TND-001", created_by="Test User")
    assert new_id is not None
    assert new_id != "TND-001"
    clone = tender_repository.get_tender(new_id)
    original = tender_repository.get_tender("TND-001")
    assert clone["status"] == "Draft"
    assert clone["created_by"] == "Test User"
    assert clone["title"] != original["title"]
    assert clone["category"] == original["category"]
    # Mutating the clone must never affect the original.
    tender_repository.update_tender(new_id, {"budget": 999999})
    assert tender_repository.get_tender("TND-001")["budget"] == original["budget"]


def test_duplicate_nonexistent_tender_returns_none():
    assert tender_repository.duplicate_tender("TND-DOES-NOT-EXIST", created_by="Test User") is None


def test_get_tender_or_default_falls_back_for_unknown_id():
    tender = tender_repository.get_tender_or_default("TND-DOES-NOT-EXIST")
    assert tender["tender_id"] == tender_repository.DEFAULT_TENDER_ID
