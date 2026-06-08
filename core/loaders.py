"""Shared loaders for the JSON masters (CIM map, charge log).

Wraps core.store so the masters load from GitHub (live) with a local fallback,
cached in session.
"""
from __future__ import annotations

import streamlit as st

from . import store


def _load(rel_path, default):
    data, _sha = store.load_json(rel_path, default=default)
    return data if data is not None else default


@st.cache_data(show_spinner=False)
def cim_customer_map():
    """{qb_customer_name: {customer_profile_id, payment_profile_id, payment_method, notes}}"""
    return _load("cim_customer_map.json", {"map": {}})


@st.cache_data(show_spinner=False)
def cim_profile_cache():
    """Snapshot of every Auth.net CIM profile fetched on last refresh — full
    catalog used by the mapping page so operators don't re-fetch on every
    page load."""
    return _load("cim_profile_cache.json", {"profiles": [], "fetched_at": None})


def clear_caches():
    cim_customer_map.clear()
    cim_profile_cache.clear()
