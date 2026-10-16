# Domain: installed SDK and control-character boundaries

Recommendation: normalize documented aliases, validate all raw accepted fields plus
the entire canonical batch before writes, and reject unknown operations/extras.
Use strict shared validation at engine entry points; REST-only models cannot
protect MCP or direct adapters. Reject forbidden controls without stripping them:
stripping changes Source identity. Specify multiline-text policy separately;
newline/tab are ordinary authored content, unlike NUL/DEL.

Installed-contract evidence: PowerShell here-string Python piped into
`.venv/Scripts/python.exe -` imported `MCPServer`, `func_metadata`, and
`RequestBodyLimitMiddleware`; `inspect.signature(MCPServer.streamable_http_app)`
and `importlib.metadata.version('mcp')` printed:

```text
mcp_version=2.3.0
streamable_http_limit_parameter=max_request_body_size: 'int' = 4194304
chunked_no_length_status=413
oversize_downstream_called=False
wrong_list_error=ValidationError;input_echo=True
unknown_accepted=True;unknown_retained=False
null_text_error=ValidationError;input_echo=True
```

The body probe directly invoked installed middleware with limit five, no
Content-Length, and two three-byte ASGI chunks. The validation probe used
`func_metadata` for `(conf:list[str]|None=None,text:str='')`, passing `conf=5`,
an unknown field, and `text=None`. This proves SDK defaults discard unknowns and
validation exceptions contain input; shared function-body validation alone cannot
sanitize SDK rejection before that body runs.

Source inspection: SDK `tools/base.py:152-156` wraps argument-validation failures
into ToolError including exception text; `server.py:453-456` logs/returns that
text. `streamable_http.py:588-594` also returns raw JSON-RPC validation text.
Configure `streamable_http_app(max_request_body_size=LIMITS['body_bytes'])` and
apply a common actual-byte ASGI limit outside REST/MCP dispatch. Sanitize both
SDK transport/tool errors and application errors; `_call` alone is insufficient.

Live DB probe: another here-string used `Db()`, `ensure_schema`, `record_source`
and `remember(settings=Settings(_env_file=None,pedigree_store_text=True))` on one
unique `consult_p021_<uuid>` graph. Actual output:

```text
graph_module_version=42201
nul_uri_error=internal
nul_text_error=internal
newline_uri_roundtrip=True
newline_text_roundtrip=True
tab_uri_roundtrip=True
tab_text_roundtrip=True
delete_uri_roundtrip=True
delete_text_roundtrip=True
owned_graph_cleanup=True
```

An initial combined-NUL/newline Source probe also failed internally and cleaned
its exact owned graph. No registry writes or historical graph changes occurred.

Confidence: high for installed behavior, medium for proposed boundary until
REST/MCP wire tests verify chunked rejection, no mutation and response/log redaction.
These probes do not prove network integration or universal Unicode handling.
