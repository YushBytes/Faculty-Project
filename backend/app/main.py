from fastapi import FastAPI

from app import __version__
from app.api.v1 import api_v1_router
from app.core.config import get_settings
from app.core.errors import register_error_handlers
from app.modules.system.router import router as system_router


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.app_name, version=__version__)
    register_error_handlers(app)
    app.include_router(system_router)  # GET /health (unversioned, for orchestration probes)
    app.include_router(api_v1_router, prefix=settings.api_v1_prefix)
    return app


app = create_app()
