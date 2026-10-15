"""Persistence for the per-class holdings CSVs (stocks / ETF / crypto).

Each class has exactly one saved file. Where it lives depends on the secrets:

* GitHub configured (`github_token` + `github_repo`): the file is read from and
  written to `<github_data_dir>/<class>.csv` on `github_branch` via the
  contents API. This is what makes uploads survive Streamlit Cloud restarts and
  show up on every device. Point `github_repo` at a PRIVATE repo — the files are
  personal holdings.
* Otherwise: a plain local file `data/<class>.csv` (gitignored).

The functions take the config explicitly so they stay testable without Streamlit.
"""
from __future__ import annotations

import base64
from dataclasses import dataclass
from pathlib import Path

import requests

CLASSES = ("stocks", "etf", "crypto")
LOCAL_DIR = Path(__file__).parent / "data"
# Pre-multi-asset installs saved the stocks file under this name.
LEGACY_STOCKS = LOCAL_DIR / "portfolio.csv"


@dataclass(frozen=True)
class GitHubConfig:
    token: str
    repo: str
    branch: str = "main"
    data_dir: str = "data"

    def path(self, cls: str) -> str:
        return f"{self.data_dir.strip('/')}/{cls}.csv"

    @property
    def headers(self) -> dict:
        return {"Authorization": f"Bearer {self.token}",
                "Accept": "application/vnd.github+json"}

    def api(self, cls: str) -> str:
        return f"https://api.github.com/repos/{self.repo}/contents/{self.path(cls)}"


def github_config(secrets) -> GitHubConfig | None:
    """Build the GitHub config from a secrets mapping, or None if not configured."""
    try:
        token = secrets.get("github_token")
        repo = secrets.get("github_repo")
        branch = secrets.get("github_branch", "main")
        data_dir = secrets.get("github_data_dir", "data")
    except Exception:  # st.secrets raises when no secrets file exists
        return None
    if not token or not repo:
        return None
    return GitHubConfig(str(token), str(repo), str(branch), str(data_dir))


def local_path(cls: str) -> Path:
    return LOCAL_DIR / f"{cls}.csv"


def load(cls: str, gh: GitHubConfig | None) -> bytes | None:
    """Return the saved CSV bytes for a class, or None if nothing is saved."""
    if gh is not None:
        r = requests.get(gh.api(cls), headers={**gh.headers, "Accept": "application/vnd.github.raw"},
                         params={"ref": gh.branch}, timeout=15)
        if r.status_code == 200:
            return r.content
        if r.status_code != 404:
            raise RuntimeError(f"GitHub read failed ({r.status_code}): {r.text[:200]}")
        return None
    p = local_path(cls)
    if p.exists():
        return p.read_bytes()
    if cls == "stocks" and LEGACY_STOCKS.exists():
        return LEGACY_STOCKS.read_bytes()
    return None


def save(cls: str, content: bytes, gh: GitHubConfig | None) -> None:
    """Replace the saved CSV for a class. Raises on failure."""
    if gh is not None:
        sha = None
        r = requests.get(gh.api(cls), headers=gh.headers, params={"ref": gh.branch}, timeout=15)
        if r.status_code == 200:
            sha = r.json().get("sha")
        payload = {"message": f"Update {gh.path(cls)} via app",
                   "content": base64.b64encode(content).decode(),
                   "branch": gh.branch}
        if sha:
            payload["sha"] = sha
        r = requests.put(gh.api(cls), headers=gh.headers, json=payload, timeout=20)
        if r.status_code not in (200, 201):
            try:
                msg = r.json().get("message", r.text)
            except Exception:
                msg = r.text
            raise RuntimeError(f"GitHub save failed ({r.status_code}): {str(msg)[:200]}")
        return
    p = local_path(cls)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(content)
