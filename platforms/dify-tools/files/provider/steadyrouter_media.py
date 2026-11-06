from typing import Any

from dify_plugin import ToolProvider
from dify_plugin.errors.model import CredentialsValidateFailedError
from srclient import SRClient, SRError


class SteadyRouterMediaProvider(ToolProvider):
    def _validate_credentials(self, credentials: dict[str, Any]) -> None:
        try:
            SRClient(credentials.get("api_key") or "").check_key()
        except SRError as exc:
            # Dify shows this type's message as it is. ToolProviderCredentialValidationError reaches the user as a traceback.
            raise CredentialsValidateFailedError(str(exc)) from exc
