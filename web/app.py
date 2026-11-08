import mimetypes
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.staticfiles import StaticFiles

from web.rendering import templates
from web.routes import admin, public, wishes

mimetypes.add_type('image/webp', '.webp')


def create_app():
    app = FastAPI(
        title='P.A.I.M.O.N. — архив сообщества',
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.add_middleware(GZipMiddleware, minimum_size=1000)
    app.mount('/static', StaticFiles(directory=Path(__file__).resolve().parent / 'static'), name='static')
    app.include_router(public.router)
    app.include_router(admin.router)
    app.include_router(wishes.router)

    @app.middleware('http')
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        response.headers['Permissions-Policy'] = 'camera=(), microphone=(), geolocation=()'
        response.headers['Content-Security-Policy'] = (
            "default-src 'self'; script-src 'self' https://telegram.org https://*.telegram.org; "
            "frame-src https://oauth.telegram.org https://www.youtube-nocookie.com "
            "https://www.youtube.com https://www.tiktok.com https://www.instagram.com; "
            "style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
            "media-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
        )
        return response

    @app.exception_handler(404)
    async def not_found(request: Request, exc):
        return templates.TemplateResponse(
            request=request, name='error.html',
            context={'message': 'Страница не найдена'}, status_code=404,
        )

    @app.exception_handler(403)
    async def forbidden(request: Request, exc):
        return templates.TemplateResponse(
            request=request, name='error.html',
            context={'message': exc.detail}, status_code=403,
        )

    return app


app = create_app()
