"""Land AI Wildfire Intelligence - FastAPI application.

Run from backend/:  uvicorn app.main:app --reload
"""
from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded

from .api import administrative, health, wildfire
from .core.config import get_settings
from .core.errors import WildfireError
from .core.rate_limit import limiter

logger = logging.getLogger('landai')

def create_app() -> FastAPI:
    app = FastAPI(title='Land AI Wildfire Intelligence', version='0.1.0',
                  description='Automated preliminary wildfire estimate (V7.6 port).')
    app.state.limiter = limiter
    @app.exception_handler(RateLimitExceeded)
    async def rate_limit_handler(_: Request, exc: RateLimitExceeded) -> JSONResponse:
        return JSONResponse(
            status_code=429,
            content={
                'status': 'error',
                'code': 'rate_limit_exceeded',
                'message': 'Too many wildfire analyses. Please wait before trying again.',
                'details': str(exc.detail),
            },
        )
    app.add_middleware(CORSMiddleware, allow_origins=get_settings().cors_origin_list,
                       allow_methods=['GET', 'POST', 'OPTIONS'], allow_headers=['*'])

    @app.exception_handler(WildfireError)
    async def wildfire_error_handler(_: Request, exc: WildfireError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content=exc.to_dict())

    @app.exception_handler(RequestValidationError)
    async def validation_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
        details = [{'field': '.'.join(str(p) for p in e['loc'][1:]) or 'body',
                    'message': e['msg']} for e in exc.errors()]
        return JSONResponse(status_code=422, content={
            'status': 'error', 'code': 'invalid_request',
            'message': 'The request is not valid: ' + '; '.join(
                f"{d['field']}: {d['message']}" for d in details),
            'details': details})

    @app.exception_handler(Exception)
    async def unexpected_handler(_: Request, exc: Exception) -> JSONResponse:
        logger.exception('Unhandled error')
        return JSONResponse(status_code=500, content={
            'status': 'error', 'code': 'internal_error',
            'message': 'Unexpected server error.', 'details': None})

    app.include_router(health.router)
    app.include_router(administrative.router)
    app.include_router(wildfire.router)
    return app


app = create_app()
