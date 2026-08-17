from fastapi import APIRouter, HTTPException

from app.schemas.style import ResumeStyle
from app.schemas.template import TemplateDefinition, TemplateListResponse
from app.services.templates.registry import get_template, list_templates

router = APIRouter(prefix="/api/templates", tags=["templates"])


@router.get("", response_model=TemplateListResponse)
def get_templates(include_inactive: bool = False):
    """Active templates in deterministic order (7.1)."""
    return TemplateListResponse(
        templates=list_templates(include_inactive=include_inactive),
        systemDefaultStyle=ResumeStyle().model_dump(),
    )


@router.get("/{template_id}", response_model=TemplateDefinition)
def get_one_template(template_id: str):
    template = get_template(template_id)
    if template is None:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "TEMPLATE_NOT_FOUND",
                "message": "The requested template does not exist.",
            },
        )
    return template
