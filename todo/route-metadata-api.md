# Route metadata API for documentation tools

wesktop should expose structured route metadata (paths, methods, path param types, query params, request body models, response_models) via a programmatic API like `router.get_routes()` or `app.openapi()`. This enables documentation tools — specifically selfdoc's planned `table-endpoint` directive — to auto-generate endpoint reference docs from the live app.

## Context

- wesktop routes have typed path params ({id:int}, {key:path}), query validation constraints, request body models (json_as), and response_model — all metadata that could be extracted.
- selfdoc already auto-generates module/function/class reference docs. Adding endpoint docs would complete the picture.
- OpenAPI (JSON spec + Swagger UI) is one option. A simpler structured dict is another. Either can feed selfdoc's directive.

## Options

1. **OpenAPI spec generation**: Produce /openapi.json from route definitions. Standard format, usable by any tool. Significant scope (~500+ lines).
2. **Structured route metadata API**: `router.get_routes()` returns a list of dicts with path, method, param types, models. Simpler, selfdoc-specific.
3. **Both**: Metadata API for programmatic access, OpenAPI for interop.

## Related

- selfdoc `table-endpoint` directive (planned, not yet implemented)
