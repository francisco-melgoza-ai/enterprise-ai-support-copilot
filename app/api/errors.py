from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.core.auth import AuthenticationError, AuthorizationError
from app.services.ticket_analysis import TicketAnalysisServiceError


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "validation_error",
                    "message": "Request validation failed.",
                    "details": _validation_details(exc),
                }
            },
        )

    @app.exception_handler(TicketAnalysisServiceError)
    async def ticket_analysis_exception_handler(
        request: Request, exc: TicketAnalysisServiceError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=503,
            content={
                "error": {
                    "code": "ticket_analysis_unavailable",
                    "message": "Ticket analysis is temporarily unavailable.",
                }
            },
        )

    @app.exception_handler(AuthenticationError)
    async def authentication_exception_handler(
        request: Request, exc: AuthenticationError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=401,
            headers={"WWW-Authenticate": "Bearer"},
            content={
                "error": {
                    "code": "authentication_failed",
                    "message": "Authentication is required.",
                }
            },
        )

    @app.exception_handler(AuthorizationError)
    async def authorization_exception_handler(
        request: Request, exc: AuthorizationError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=403,
            content={
                "error": {
                    "code": "authorization_failed",
                    "message": "Insufficient permissions.",
                }
            },
        )


def _validation_details(exc: RequestValidationError) -> list[dict[str, Any]]:
    details: list[dict[str, Any]] = []
    for error in exc.errors():
        details.append(
            {
                "loc": error.get("loc", ()),
                "msg": error.get("msg", ""),
                "type": error.get("type", ""),
            }
        )
    return details
