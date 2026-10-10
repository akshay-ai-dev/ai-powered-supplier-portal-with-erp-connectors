"""Buyer *New requirement* extraction: a PDF or image in, a reviewable requirement draft out.

This reuses the shared OpenAI PDF/image upload core in `extractor.run` (type/size validation,
base64 file/image content part, strict structured-output call) with the buyer prompt and schema, then
applies the deterministic buyer rules. It creates nothing — the caller returns the draft only.
"""

from . import buyer_rules, extractor
from .buyer_prompts import BUYER_DRAFT_JSON_SCHEMA, BUYER_SYSTEM_PROMPT, BUYER_USER_INSTRUCTION
from .buyer_schemas import RequirementDraft

MAX_BYTES = extractor.MAX_BYTES


def extract(
    filename: str,
    data: bytes,
    content_type: str | None,
    *,
    client=None,
    model: str | None = None,
) -> dict:
    """Validate the upload, ask OpenAI for a structured requirement draft, tidy it, return a dict."""
    raw = extractor.run(
        filename,
        data,
        content_type,
        system_prompt=BUYER_SYSTEM_PROMPT,
        user_instruction=BUYER_USER_INSTRUCTION,
        json_schema=BUYER_DRAFT_JSON_SCHEMA,
        schema_name="requirement_draft",
        client=client,
        model=model,
    )
    draft = buyer_rules.finalize(RequirementDraft.model_validate(raw))
    return draft.model_dump()
