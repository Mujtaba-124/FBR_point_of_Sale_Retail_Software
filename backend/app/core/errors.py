"""Consistent error responses: {"error": {"code": "...", "message": "..."}}."""

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


class AppError(Exception):
    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.headers = headers


class NotAuthenticated(AppError):
    def __init__(self, message: str = "Authentication required.") -> None:
        super().__init__(401, "not_authenticated", message)


class PermissionDenied(AppError):
    def __init__(
        self, message: str = "You do not have permission to access this resource."
    ) -> None:
        super().__init__(403, "permission_denied", message)


def error_body(code: str, message: str) -> dict[str, dict[str, str]]:
    return {"error": {"code": code, "message": message}}


def _clear_session_cookies(request: Request, response: JSONResponse) -> None:
    # Imported lazily to avoid a cycle (sessions -> errors).
    from app.services.sessions import clear_auth_cookies, request_has_session_cookie

    if request_has_session_cookie(request):
        clear_auth_cookies(response)


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(request: Request, exc: AppError) -> JSONResponse:
        response = JSONResponse(
            status_code=exc.status_code,
            content=error_body(exc.code, exc.message),
            headers=exc.headers,
        )
        if isinstance(exc, NotAuthenticated):
            _clear_session_cookies(request, response)
        return response

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content=error_body("validation_error", "The request is invalid."),
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = {404: "not_found", 405: "method_not_allowed"}.get(exc.status_code, "http_error")
        return JSONResponse(
            status_code=exc.status_code,
            content=error_body(code, str(exc.detail)),
            headers=getattr(exc, "headers", None),
        )
