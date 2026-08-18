from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from app.schemas.layout import LayoutError, default_layout
from app.schemas.style import ResumeStyle
from app.schemas.template import TemplateDefinition, TemplateListResponse
from app.services.templates import store
from app.services.templates.registry import get_template, list_templates
from app.services.templates.store import TemplateNotFound, TemplateReadOnly

router = APIRouter(prefix="/api/templates", tags=["templates"])


class CreateTemplateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    description: str = ""
    # Omit to start from the default layout.
    layout: dict | None = None
    defaultStyle: dict = Field(default_factory=dict)
    ownerProfileId: str | None = None
    # Copy an existing template (built-in or user) instead of starting blank.
    duplicateOf: str | None = None


class UpdateTemplateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    description: str | None = None
    layout: dict | None = None
    defaultStyle: dict | None = None
    active: bool | None = None


def _bad_request(code: str, message: str) -> HTTPException:
    return HTTPException(status_code=400, detail={"code": code, "message": message})


def _not_found() -> HTTPException:
    return HTTPException(
        status_code=404,
        detail={"code": "TEMPLATE_NOT_FOUND", "message": "The requested template does not exist."},
    )


@router.get("", response_model=TemplateListResponse)
def get_templates(include_inactive: bool = False):
    """Built-in and user templates in deterministic order (7.1)."""
    return TemplateListResponse(
        templates=list_templates(include_inactive=include_inactive),
        systemDefaultStyle=ResumeStyle().model_dump(),
    )


@router.get("/default-layout")
def get_default_layout():
    """Starting document for a new template, so the builder need not hardcode it."""
    return default_layout().model_dump()


@router.post("", response_model=TemplateDefinition, status_code=201)
def create_template(payload: CreateTemplateRequest):
    try:
        if payload.duplicateOf:
            source = get_template(payload.duplicateOf)
            if source is None:
                raise _bad_request(
                    "TEMPLATE_NOT_FOUND", f"Cannot duplicate unknown template {payload.duplicateOf!r}"
                )
            # Duplicating a built-in needs an explicit layout, since code
            # renderers have no layout document to copy.
            layout = payload.layout
            if layout is None and not source.layout:
                layout = default_layout().model_dump()
            return store.duplicate_template(source, name=payload.name or None, layout=layout)

        return store.create_user_template(
            name=payload.name,
            description=payload.description,
            layout=payload.layout,
            default_style=payload.defaultStyle,
            owner_profile_id=payload.ownerProfileId,
        )
    except LayoutError as exc:
        raise _bad_request("INVALID_LAYOUT", str(exc)) from exc
    except ValueError as exc:
        raise _bad_request("INVALID_TEMPLATE", str(exc)) from exc


@router.get("/{template_id}", response_model=TemplateDefinition)
def get_one_template(template_id: str):
    template = get_template(template_id)
    if template is None:
        raise _not_found()
    return template


@router.put("/{template_id}", response_model=TemplateDefinition)
def update_template(template_id: str, payload: UpdateTemplateRequest):
    try:
        return store.update_user_template(
            template_id,
            name=payload.name,
            description=payload.description,
            layout=payload.layout,
            default_style=payload.defaultStyle,
            active=payload.active,
        )
    except TemplateNotFound as exc:
        raise _not_found() from exc
    except TemplateReadOnly as exc:
        raise HTTPException(
            status_code=403,
            detail={
                "code": "TEMPLATE_READ_ONLY",
                "message": "Built-in templates cannot be edited. Duplicate it first.",
            },
        ) from exc
    except LayoutError as exc:
        raise _bad_request("INVALID_LAYOUT", str(exc)) from exc
    except ValueError as exc:
        raise _bad_request("INVALID_TEMPLATE", str(exc)) from exc


@router.delete("/{template_id}", status_code=204)
def delete_template(template_id: str):
    try:
        store.delete_user_template(template_id)
    except TemplateNotFound as exc:
        raise _not_found() from exc
    except TemplateReadOnly as exc:
        raise HTTPException(
            status_code=403,
            detail={
                "code": "TEMPLATE_READ_ONLY",
                "message": "Built-in templates cannot be deleted.",
            },
        ) from exc
