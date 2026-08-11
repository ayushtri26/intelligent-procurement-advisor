"""Tests for rule-based notification generation (src/notifications.py)."""
import pandas as pd
import streamlit as st

from src import notifications


def setup_function():
    st.session_state.clear()


def _fake_ranked_df(anomalous_ids=(), top_score=87.7):
    rows = [
        {"vendor_id": "V001", "vendor_name": "Alpha Corp", "overall_score": top_score, "is_anomalous": "V001" in anomalous_ids},
        {"vendor_id": "V002", "vendor_name": "Beta Inc", "overall_score": top_score - 5, "is_anomalous": "V002" in anomalous_ids},
    ]
    return pd.DataFrame(rows)


def test_sync_generates_high_risk_notification_for_anomalous_vendor():
    df = _fake_ranked_df(anomalous_ids=("V002",))
    notifications.sync_from_ranked_df(df)
    notifs = notifications.get_notifications()
    high_risk = [n for n in notifs if n["category"] == "High Risk Vendor"]
    assert len(high_risk) == 1
    assert "Beta Inc" in high_risk[0]["title"]


def test_sync_is_idempotent_no_duplicate_high_risk_entries():
    df = _fake_ranked_df(anomalous_ids=("V002",))
    notifications.sync_from_ranked_df(df)
    notifications.sync_from_ranked_df(df)
    notifications.sync_from_ranked_df(df)
    notifs = [n for n in notifications.get_notifications() if n["category"] == "High Risk Vendor"]
    assert len(notifs) == 1


def test_score_updated_notification_fires_only_on_real_change():
    df1 = _fake_ranked_df(top_score=80.0)
    notifications.sync_from_ranked_df(df1)
    assert not [n for n in notifications.get_notifications() if n["category"] == "Score Updated"]  # first load, no prior score

    df2 = _fake_ranked_df(top_score=85.0)
    notifications.sync_from_ranked_df(df2)
    score_updates = [n for n in notifications.get_notifications() if n["category"] == "Score Updated"]
    assert len(score_updates) == 1

    # re-sync with same score -> no new notification
    notifications.sync_from_ranked_df(df2)
    score_updates_after = [n for n in notifications.get_notifications() if n["category"] == "Score Updated"]
    assert len(score_updates_after) == 1


def test_notify_ai_recommendation_ready():
    notifications.notify_ai_recommendation_ready("Everest Logistics Partners")
    notifs = notifications.get_notifications()
    assert any(n["category"] == "AI Recommendation Ready" for n in notifs)


def test_mark_read_and_unread_count():
    notifications.notify_ai_recommendation_ready("Vendor X")
    assert notifications.unread_count() == 1
    notif_id = notifications.get_notifications()[0]["id"]
    notifications.mark_read(notif_id)
    assert notifications.unread_count() == 0


def test_mark_all_read():
    notifications.notify_ai_recommendation_ready("Vendor X")
    notifications.notify_tender_deadline()
    assert notifications.unread_count() == 2
    notifications.mark_all_read()
    assert notifications.unread_count() == 0


def test_sync_contract_expiry_idempotent():
    awarded = [{"vendor_name": "Vendor X", "vendor_id": "V009", "awarded_at": "2026-01-01 10:00:00"}]
    notifications.sync_contract_expiry(awarded)
    notifications.sync_contract_expiry(awarded)
    matches = [n for n in notifications.get_notifications() if n["category"] == "Contract Expiry"]
    assert len(matches) == 1


def test_empty_ranked_df_does_not_raise():
    notifications.sync_from_ranked_df(pd.DataFrame())
    assert notifications.get_notifications() == []
