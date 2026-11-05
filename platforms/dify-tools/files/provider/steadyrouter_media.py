from typing import Any

from dify_plugin import ToolProvider
from dify_plugin.errors.tool import ToolProviderCredentialValidationError
from srclient import SRClient, SRError


class SteadyRouterMediaProvider(ToolProvider):
    def _validate_credentials(self, credentials: dict[str, Any]) -> None:
        try:
            SRClient(credentials.get("api_key") or "").check_key()
        except SRError as exc:
            raise ToolProviderCredentialValidationError(str(exc)) from exc
