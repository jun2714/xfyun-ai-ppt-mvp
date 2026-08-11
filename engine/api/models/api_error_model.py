from fastapi import HTTPException
from pydantic import BaseModel
from typing import Optional


class APIErrorModel(BaseModel):
    status_code: int
    detail: str
    code: Optional[str] = None
    stage: Optional[str] = None
    slide_number: Optional[int] = None
    incurred_cost: Optional[bool] = None
    retryable: Optional[bool] = None

    @classmethod
    def from_exception(cls, e: Exception) -> "APIErrorModel":
        if isinstance(e, HTTPException):
            detail = e.detail
            if isinstance(detail, dict):
                message = str(detail.get("message") or detail.get("detail") or detail)
            else:
                message = str(detail)
            return APIErrorModel(
                status_code=e.status_code,
                detail=message,
                code=getattr(e, "code", None),
                stage=getattr(e, "stage", None),
                slide_number=getattr(e, "slide_number", None),
                incurred_cost=getattr(e, "incurred_cost", None),
                retryable=getattr(e, "retryable", None),
            )
        return APIErrorModel(status_code=500, detail=str(e))
