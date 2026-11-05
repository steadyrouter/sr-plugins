"""The fixed gateway address and a key check that spends nothing."""

import requests
from dify_plugin.errors.model import CredentialsValidateFailedError

from models._site import API_BASE

ENDPOINT = f"{API_BASE}/v1"


def set_endpoint(credentials: dict) -> None:
    credentials["endpoint_url"] = ENDPOINT


def check_key(credentials: dict) -> None:
    """GET /v1/models is free. The base classes would send a paid chat request instead."""
    key = (credentials.get("api_key") or "").strip()
    if not key:
        raise CredentialsValidateFailedError("An API key is required.")
    try:
        reply = requests.get(f"{ENDPOINT}/models", headers={"Authorization": f"Bearer {key}"}, timeout=20)
    except requests.RequestException as exc:
        raise CredentialsValidateFailedError("Could not reach SteadyRouter. Check the network and try again.") from exc
    if reply.status_code == 401:
        raise CredentialsValidateFailedError("The API key is wrong, disabled, expired or out of its spending cap.")
    if reply.status_code != 200:
        raise CredentialsValidateFailedError(f"SteadyRouter answered with HTTP {reply.status_code}. Try again later.")
