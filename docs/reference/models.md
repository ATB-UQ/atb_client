# Models

Every response is a `pydantic` model (extra fields kept, so a field the server adds reaches
`model.model_extra` before the client is updated). Timestamps are timezone-aware UTC
`datetime`s.

::: atb_client.models
    options:
      show_submodules: false
      filters:
        - "!^_"
