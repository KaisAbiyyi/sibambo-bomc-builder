"""BMB-032: silabs-generator handoff. Survey / form / room-brief -> the same agent builder API.

Standard library plus the Builder's own packages only. Nothing here opens a socket, calls a model
or needs a credential: the lowering is a deterministic function and the submission goes through the
real stdio MCP server exactly like any other agent.
"""
from integration.generator.brief import (  # noqa: F401
    BriefError, FORM, MAX_BYTES, MAX_ROOMS, SCHEMA, SURVEY, brief_sha256, lower, normalize_form,
    normalize_survey, to_brief, validate_brief,
)
