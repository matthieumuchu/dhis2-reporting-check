"""A small, readable client for the DHIS2 Web API.

Only four calls are needed for this project:
  /api/me                     -> which organisation unit the user sits at (the root of the analysis)
  /api/dataSets               -> find the monthly report form by name
  /api/dataElements           -> find the value to check for outliers by name
  /api/analytics              -> pull reporting metrics and values, by facility and month
"""
from __future__ import annotations

import pandas as pd
import requests


class DHIS2:
    def __init__(self, base_url: str, user: str, password: str, timeout: int = 120):
        self.base = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.auth = (user, password)
        self.timeout = timeout

    def get(self, path: str, **params) -> dict:
        resp = self.session.get(f"{self.base}/api/{path}", params=params, timeout=self.timeout)
        if resp.status_code == 401:
            raise SystemExit("401 Unauthorized: wrong username/password, or the URL redirected and "
                             "dropped the login. Use the final server URL (see GUIDE.md).")
        resp.raise_for_status()
        try:
            return resp.json()
        except ValueError:                      # got a web page (usually a login page) instead of data
            raise SystemExit(
                f"{self.base} returned a web page instead of API data. Open https://play.dhis2.org in a "
                "browser, click a demo instance, and copy its address (it contains 'play.im.dhis2.org/...') "
                "into DHIS2_URL in your .env file. For your own server, use the address you log in at.")

    # --- metadata ---------------------------------------------------------
    def root_org_unit(self) -> dict:
        me = self.get("me", fields="organisationUnits[id,name]")
        return me["organisationUnits"][0]

    def find_one(self, endpoint: str, name: str) -> dict:
        found = self.get(endpoint, filter=f"name:eq:{name}", fields="id,name", paging="false")[endpoint]
        if not found:
            options = self.get(endpoint, fields="name", paging="false")[endpoint]
            raise SystemExit(f"No {endpoint} called '{name}'. Available: "
                             + ", ".join(sorted(o["name"] for o in options)[:40]))
        return found[0]

    # --- analytics ----------------------------------------------------------
    def analytics(self, dx: list[str], ou: str, pe: str) -> dict:
        """Raw analytics response with one row per (dx, ou, pe) combination."""
        return self.get("analytics",
                        dimension=[f"dx:{';'.join(dx)}", f"ou:{ou}", f"pe:{pe}"],
                        displayProperty="NAME", showHierarchy="true")


def analytics_to_frame(payload: dict) -> pd.DataFrame:
    """Turn an analytics JSON response into a tidy table with readable names.

    The response lists column names in `headers`, the data in `rows` and the
    names of every ID in `metaData.items`.
    """
    cols = [h["name"] for h in payload["headers"]]
    df = pd.DataFrame(payload.get("rows", []), columns=cols)
    if df.empty:
        return pd.DataFrame(columns=["dx", "ou", "pe", "value", "ou_name", "district"])
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    items = payload.get("metaData", {}).get("items", {})
    df["ou_name"] = df["ou"].map(lambda u: items.get(u, {}).get("name", u))
    hierarchy = payload.get("metaData", {}).get("ouHierarchy", {})
    # hierarchy path looks like "rootId/districtId/chiefdomId" -> take the district (2nd level)
    df["district"] = df["ou"].map(
        lambda u: items.get(hierarchy.get(u, "").split("/")[1], {}).get("name", "Unknown")
        if len(hierarchy.get(u, "").split("/")) > 1 else "Unknown")
    return df
