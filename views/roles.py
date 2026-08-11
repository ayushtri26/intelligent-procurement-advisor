"""Roles — the role → page-access permission matrix (src/rbac.py)."""
import pandas as pd
import streamlit as st

from src import rbac, ui_components

st.title("Roles")
st.caption("Each role sees only the navigation sections it's permitted to access. Role is assigned automatically at sign-in (src/rbac.py assign_role_from_name) and can't be changed manually.")

matrix = pd.DataFrame(
    {role: {page: ("Yes" if page in rbac.PAGE_PERMISSIONS[role] else "") for page in rbac.ALL_PAGE_KEYS} for role in rbac.ROLES}
)
ui_components.data_table(matrix.reset_index(names="Page"))

st.subheader("Approval stage permissions")
st.write(f"**Manager Approval stage:** {', '.join(sorted(rbac.MANAGER_APPROVAL_ROLES))}")
st.write(f"**Director Approval stage:** {', '.join(sorted(rbac.DIRECTOR_APPROVAL_ROLES))}")
st.write(f"**Can edit scoring weights:** {', '.join(sorted(rbac.WEIGHT_EDIT_ROLES))}")
