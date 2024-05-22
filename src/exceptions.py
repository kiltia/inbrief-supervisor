from asgi_correlation_id import correlation_id
from fastapi import status
from fastapi.requests import Request
from fastapi.responses import JSONResponse


class ComponentException(Exception):
    def __init__(
        self,
        component: str,
        component_status_code: int,
        component_error: str,
        debug: dict,
    ):
        self.component = component
        self.component_status_code = component_status_code
        self.component_error = component_error
        self.debug = debug


async def component_exception_handler(_: Request, exc: ComponentException):
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content={
            "component": exc.component,
            "component_status_code": exc.component_status_code,
            "component_error": exc.component_error,
            "debug": exc.debug,
        },
        headers={"X-Request-ID": correlation_id.get() or ""},
    )


async def supervisor_exception_handler(_: Request, exc: Exception):
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "component": "SUPERVISOR",
            "component_status_code": status.HTTP_500_INTERNAL_SERVER_ERROR,
            "component_error": repr(exc),
        },
        headers={"X-Request-ID": correlation_id.get() or ""},
    )
