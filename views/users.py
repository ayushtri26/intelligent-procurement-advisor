"""Users — a seeded, in-memory user directory. There is no real backend;
this simulates user administration for demo purposes only."""
import streamlit as st

from src import audit, rbac, ui_components

if "seeded_users" not in st.session_state:
    st.session_state.seeded_users = [
        {"Name": "Ayush Tripathi", "Role": "Administrator", "Email": "ayush@example.com", "Status": "Active"},
        {"Name": "Priya Shah", "Role": "Procurement Manager", "Email": "priya@example.com", "Status": "Active"},
        {"Name": "Alex Kim", "Role": "Executive", "Email": "alex@example.com", "Status": "Active"},
        {"Name": "Jordan Lee", "Role": "Auditor", "Email": "jordan@example.com", "Status": "Active"},
        {"Name": "Vendor Portal", "Role": "Vendor", "Email": "vendor-portal@example.com", "Status": "Active"},
    ]

st.title("Users")
st.caption("Simulated in-memory user directory — no real accounts or authentication are created.")

ui_components.data_table(st.session_state.seeded_users)

with st.expander("Add a user"):
    name = st.text_input("Name", key="new_user_name")
    role = st.selectbox("Role", rbac.ROLES, key="new_user_role")
    email = st.text_input("Email", key="new_user_email")
    if st.button("Add user"):
        if name.strip():
            st.session_state.seeded_users.append({"Name": name.strip(), "Role": role, "Email": email.strip(), "Status": "Active"})
            audit.log_action("User Added", "Administration", name.strip(), new=role, status="Success")
            st.rerun()
        else:
            st.warning("Enter a name first.")
