"""One-click PDF report generation.

Every generator here formats data that some other module already computed
(src.dashboard, src.analytics_tools) — no new business logic. fpdf2's core
fonts are Latin-1 only, so all text is sanitized before writing to avoid
encoding errors on the emoji/arrows/en-dashes used elsewhere in the UI.
"""
from __future__ import annotations

from datetime import datetime

import pandas as pd
from fpdf import FPDF


def _sanitize(text) -> str:
    return str(text).encode("latin-1", "replace").decode("latin-1")


def _line(pdf: FPDF, h: float, text: str) -> None:
    """multi_cell wrapper that always returns the cursor to the left margin on
    the next line — fpdf2's own default (new_x=XPos.RIGHT) leaves the cursor
    at the right edge, which breaks every subsequent stacked call."""
    pdf.multi_cell(0, h, _sanitize(text), new_x="LMARGIN", new_y="NEXT")


def _new_pdf(title: str) -> FPDF:
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 18)
    pdf.cell(0, 12, _sanitize(title), ln=True)
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(120, 120, 120)
    pdf.cell(0, 6, _sanitize(f"Generated {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"), ln=True)
    pdf.set_text_color(0, 0, 0)
    pdf.ln(4)
    return pdf


def _write_heading(pdf: FPDF, text: str) -> None:
    pdf.set_font("Helvetica", "B", 13)
    pdf.ln(3)
    pdf.cell(0, 8, _sanitize(text), ln=True)
    pdf.set_font("Helvetica", "", 10)


def _write_kv(pdf: FPDF, label: str, value) -> None:
    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(50, 6, _sanitize(label), new_x="RIGHT", new_y="TOP")
    pdf.set_font("Helvetica", "", 10)
    _line(pdf, 6, value)


def _write_bullets(pdf: FPDF, items: list) -> None:
    pdf.set_font("Helvetica", "", 10)
    for item in items:
        _line(pdf, 6, f"- {item}")


def _write_table(pdf: FPDF, headers: list[str], rows: list[list], col_width: float | None = None) -> None:
    pdf.set_font("Helvetica", "B", 9)
    n = len(headers)
    width = col_width or (190 / n)
    for h in headers:
        pdf.cell(width, 7, _sanitize(h), border=1)
    pdf.ln()
    pdf.set_font("Helvetica", "", 9)
    for row in rows:
        for cell in row:
            pdf.cell(width, 7, _sanitize(cell), border=1)
        pdf.ln()


def _finalize(pdf: FPDF) -> bytes:
    data = pdf.output()
    if isinstance(data, (bytearray, bytes)):
        return bytes(data)
    return data.encode("latin-1")


def generate_executive_report(kpis: dict, top_bundle: dict) -> bytes:
    pdf = _new_pdf("Executive Procurement Report")
    rec = top_bundle["recommended_vendor"]
    _write_heading(pdf, "Recommended Vendor")
    _write_kv(pdf, "Vendor:", f"{rec['vendor_name']} ({rec['vendor_id']})")
    _write_kv(pdf, "Overall Score:", f"{rec['overall_score']}/100")
    _write_kv(pdf, "Confidence:", f"{kpis['confidence']:.0f}% ({top_bundle['confidence']})")
    _write_kv(pdf, "Anomaly Status:", "Flagged" if top_bundle["is_anomalous"] else "Not flagged")

    _write_heading(pdf, "Key Reasons")
    _write_bullets(pdf, top_bundle["key_reasons"])

    if top_bundle["trade_offs"]:
        _write_heading(pdf, "Trade-offs")
        _write_bullets(pdf, top_bundle["trade_offs"])

    _write_heading(pdf, "Due Diligence")
    _write_bullets(pdf, top_bundle["due_diligence"])

    _write_heading(pdf, "Portfolio Summary")
    _write_kv(pdf, "Vendors Evaluated:", kpis["vendors_evaluated"])
    _write_kv(pdf, "Qualified Vendors:", kpis["qualified_vendors"])
    _write_kv(pdf, "Flagged Anomalous:", kpis["anomalous_count"])
    _write_kv(pdf, "Risk Level:", kpis["risk_level"])

    pdf.ln(4)
    pdf.set_font("Helvetica", "I", 8)
    _line(pdf, 5, "This report is a recommendation only. Final vendor selection requires explicit human approval.")
    return _finalize(pdf)


def generate_vendor_summary_report(vendor_explain: dict) -> bytes:
    rec = vendor_explain["record"]
    pdf = _new_pdf(f"Vendor Summary: {rec['vendor_name']}")
    _write_kv(pdf, "Vendor ID:", rec["vendor_id"])
    _write_kv(pdf, "Category:", rec.get("category", "N/A"))
    _write_kv(pdf, "Overall Score:", f"{rec['overall_score']}/100")
    _write_kv(pdf, "Rank:", rec.get("rank", "N/A"))
    _write_kv(pdf, "Anomaly Status:", "Flagged" if rec["is_anomalous"] else "Not flagged")
    _write_kv(pdf, "Confidence:", vendor_explain.get("confidence", "N/A"))

    _write_heading(pdf, "Feature Scores")
    _write_table(
        pdf,
        ["Price", "Delivery", "Quality", "Compliance", "Experience", "Financial"],
        [[rec["price_score"], rec["delivery_score"], rec["quality_score"], rec["compliance_score"], rec["experience_score"], rec["financial_stability_score"]]],
    )

    _write_heading(pdf, "Strengths")
    _write_bullets(pdf, vendor_explain.get("strengths") or ["None identified"])
    _write_heading(pdf, "Risks")
    _write_bullets(pdf, vendor_explain.get("risks") or ["None identified"])
    _write_heading(pdf, "Recommended Actions")
    _write_bullets(pdf, vendor_explain.get("due_diligence", []))
    return _finalize(pdf)


def generate_risk_report(risk_matrix: pd.DataFrame, compliance_risks: pd.DataFrame) -> bytes:
    pdf = _new_pdf("Procurement Risk Report")
    anomalous = risk_matrix[risk_matrix["is_anomalous"] == True]  # noqa: E712
    _write_heading(pdf, f"Anomalous Vendors ({len(anomalous)})")
    if not anomalous.empty:
        _write_table(
            pdf,
            ["Vendor", "Likelihood", "Impact"],
            [[r["vendor_name"], f"{r['likelihood']:.0f}", f"{r['impact']:.0f}"] for _, r in anomalous.iterrows()],
        )
    else:
        _line(pdf, 6, "None.")

    _write_heading(pdf, f"Compliance Risk Vendors ({len(compliance_risks)})")
    if not compliance_risks.empty:
        _write_table(
            pdf,
            ["Vendor", "Compliance Score", "Violations"],
            [[r["vendor_name"], f"{r['compliance_score']:.0f}", int(r.get("compliance_violations", 0))] for _, r in compliance_risks.iterrows()],
        )
    else:
        _line(pdf, 6, "None.")
    return _finalize(pdf)


def generate_insights_report(insights: list[str]) -> bytes:
    pdf = _new_pdf("Procurement Insights")
    _write_bullets(pdf, insights)
    return _finalize(pdf)


def generate_savings_report(savings_df: pd.DataFrame) -> bytes:
    pdf = _new_pdf("Savings Opportunities (Illustrative)")
    pdf.set_font("Helvetica", "I", 9)
    _line(pdf, 6, "Figures below compare quoted price to market average price and are illustrative estimates, not audited savings.")
    pdf.ln(2)
    if not savings_df.empty:
        _write_table(
            pdf,
            ["Vendor", "Quoted Price", "Market Avg", "Delta"],
            [
                [r["vendor_name"], f"{r['quoted_price']:,.0f}", f"{r['market_avg_price']:,.0f}", f"{r['delta']:,.0f}"]
                for _, r in savings_df.iterrows()
            ],
        )
    else:
        _line(pdf, 6, "No pricing data available.")
    return _finalize(pdf)
