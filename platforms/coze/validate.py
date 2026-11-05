"""Check a Coze plugin OpenAPI file against Coze's import rules, without Coze.

The rules are copied from Coze Studio's own import code (open source, Apache-2.0), commit
fefb05ff27be1da939612fbf9faf5db62583b8ae of github.com/coze-dev/coze-studio:
  backend/crossdomain/plugin/model/openapi.go   Openapi3T.Validate, Openapi3Operation.Validate,
                                                validateOpenapi3RequestBody / Parameters / Responses,
                                                ToEinoSchemaParameterInfo
  backend/crossdomain/plugin/model/toolinfo.go  ToolInfo.ToReqAPIParameter / ToRespAPIParameter / toAPIParameter
  backend/crossdomain/plugin/convert/format.go  the only `format` values Coze accepts (file kinds)
  backend/crossdomain/plugin/convert/param.go   the only `type` values Coze accepts
The commercial coze.com / coze.cn may differ; a real import there is the final check (launch checklist).
Coze's own importer is not run here: these are its rules, copied by hand.

On top: the general OpenAPI 3.0 schema (openapi-spec-validator, if installed) and our own rules
(Authorization header, no unions, no free-form objects, the texts every plugin must carry).
"""

from __future__ import annotations

from urllib.parse import urlparse

TYPES = {"string", "integer", "number", "object", "array", "boolean"}  # convert/param.go
FORMATS = {"file_url", "image_url", "doc_url", "ppt_url", "code_url", "excel_url", "zip_url", "video_url",
           "audio_url", "txt_url"}  # convert/format.go
BODY_MEDIA = {"application/json", "application/problem+json", "application/x-www-form-urlencoded",
              "application/x-yaml", "application/yaml"}  # openapi.go mediaTypeArray
METHODS = {"get", "put", "post", "delete", "options", "head", "patch", "trace"}
UNIONS = ("oneOf", "anyOf", "allOf", "not")


def _schema_problems(schema: dict, where: str, *, top_param: bool = False) -> list[str]:
    """toAPIParameter / ToEinoSchemaParameterInfo on one schema, recursively."""
    out = []
    if not isinstance(schema, dict):
        return [f"{where}: schema is required"]
    if "$ref" in schema:
        out.append(f"{where}: $ref is not used in our files (Coze resolves it, but keep files flat)")
    for key in UNIONS:
        if key in schema:
            out.append(f"{where}: {key} is not supported by the Coze editor (it turns unions into an untyped field)")
    typ = schema.get("type")
    if typ not in TYPES:
        out.append(f"{where}: the type '{typ}' is invalid")
    fmt = schema.get("format")
    if fmt is not None and fmt not in FORMATS:
        out.append(f"{where}: the format '{fmt}' is invalid (Coze reads format as a file kind)")
    if typ == "object":
        if top_param:
            out.append(f"{where}: the type of parameter cannot be 'object'")
        props = schema.get("properties")
        if not props:
            out.append(f"{where}: object without properties (Coze drops or rejects free-form objects)")
        for name, prop in (props or {}).items():
            out += _schema_problems(prop, f"{where}.{name}")
        for name in schema.get("required", []):
            if name not in (props or {}):
                out.append(f"{where}: required field '{name}' is not a property")
    if typ == "array":
        items = schema.get("items")
        if not isinstance(items, dict):
            out.append(f"{where}: the item schema is required")
        else:
            if top_param and items.get("type") in ("object", "array"):
                out.append(f"{where}: the item type of parameter cannot be 'object' or 'array'")
            out += _schema_problems(items, f"{where}[]")
    if "enum" in schema and "default" in schema and schema["default"] not in schema["enum"]:
        out.append(f"{where}: default is not one of the enum values")
    return out


def coze_rules(doc: dict) -> list[str]:
    out = []
    info = doc.get("info") or {}
    if not info:
        out.append("info is required")
    if not info.get("title"):
        out.append("the title of info is required")
    if not info.get("description"):
        out.append("the description of info is required")
    servers = doc.get("servers") or []
    if len(servers) != 1:
        out.append("server is required and only one server is allowed")
    else:
        url = servers[0].get("url", "")
        if not urlparse(url).netloc:
            out.append(f"invalid server url '{url}'")
        if len(url) > 512:
            out.append(f"server url '{url}' is too long")
    for path, item in (doc.get("paths") or {}).items():
        for method, op in item.items():
            if method not in METHODS:
                continue
            where = f"{method.upper()} {path}"
            if not op.get("operationId"):
                out.append(f"{where}: operationID is required")
            if not op.get("summary"):
                out.append(f"{where}: summary is required")
            body = op.get("requestBody")
            if body is not None:
                content = body.get("content") or {}
                if not content:
                    out.append(f"{where}: request body is required")
                elif len(content) != 1:
                    out.append(f"{where}: request body only supports one media type")
                else:
                    media, mtype = next(iter(content.items()))
                    if media not in BODY_MEDIA:
                        out.append(f"{where}: invalid media type '{media}'")
                    schema = (mtype or {}).get("schema")
                    if not schema:
                        out.append(f"{where}: request body schema is required")
                    elif schema.get("type") != "object":
                        out.append(f"{where}: request body only supports 'object' type")
                    else:
                        out += _schema_problems(schema, f"{where} body")
            for param in op.get("parameters") or []:
                name = param.get("name")
                schema = param.get("schema")
                if not schema:
                    out.append(f"{where}: parameter schema is required")
                    continue
                if not param.get("in"):
                    out.append(f"{where}: parameter location is required")
                if param.get("in") == "body":
                    out.append(f"{where}: the location of parameter '{name}' cannot be 'body'")
                if param.get("in") == "path" and schema.get("type") == "array":
                    out.append(f"{where}: the type of parameter '{name}' cannot be 'array'")
                out += _schema_problems(schema, f"{where} param {name}", top_param=True)
            responses = op.get("responses") or {}
            codes = set(responses)
            if codes and codes not in ({"200"}, {"200", "default"}):
                out.append(f"{where}: response only supports '200' status")
            ok = responses.get("200")
            if codes and not ok:
                out.append(f"{where}: response only supports '200' status")
            if ok:
                content = ok.get("content") or {}
                if len(content) != 1 or "application/json" not in content:
                    out.append(f"{where}: response only supports 'application/json' media type")
                else:
                    schema = content["application/json"].get("schema")
                    if not schema:
                        out.append(f"{where}: the media type schema of response is required")
                    elif schema.get("type") != "object":
                        out.append(f"{where}: response body only supports 'object' type")
                    else:
                        out += _schema_problems(schema, f"{where} response")
    return out


def our_rules(doc: dict, *, keep_days: int) -> list[str]:
    out = []
    desc = (doc.get("info") or {}).get("description", "")
    for needle, why in (("steadyrouter.com/sign-up?aff=", "the get-a-key link with aff"),
                        ("10", "the 10-minute node timeout"), (str(keep_days), "how long files are kept")):
        if needle not in desc:
            out.append(f"info.description must mention {why}")
    url = (doc.get("servers") or [{}])[0].get("url", "")
    if "workers.dev" in url or not url.startswith("https://"):
        out.append(f"server url '{url}' must be our own https host, not workers.dev")
    for path, item in (doc.get("paths") or {}).items():
        for method, op in item.items():
            if method not in METHODS:
                continue
            where = f"{method.upper()} {path}"
            keys = [p for p in op.get("parameters") or [] if p.get("name") == "Authorization"]
            if len(keys) != 1 or keys[0].get("in") != "header" or not keys[0].get("required"):
                out.append(f"{where}: needs exactly one required Authorization header parameter")
            elif {"default", "example", "examples"} & (set(keys[0]) | set(keys[0].get("schema") or {})):
                out.append(f"{where}: the Authorization parameter must not carry a default or example")
    return out


def spec_problems(doc: dict) -> list[str]:
    try:
        from openapi_spec_validator import validate
    except ImportError:
        return []
    try:
        validate(doc)
    except Exception as err:  # noqa: BLE001 - any validation error is a finding
        return [f"OpenAPI 3.0: {str(err).splitlines()[0]}"]
    return []


def problems(doc: dict, *, keep_days: int) -> list[str]:
    return spec_problems(doc) + coze_rules(doc) + our_rules(doc, keep_days=keep_days)
