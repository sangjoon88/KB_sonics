from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse

from app.auth import AdminRequired
from app.routers import admin, api, arcade, pages
from app.routers.common import PinChangeRequired
from app.services.ops import OpError

app = FastAPI(title="KB SONICS", docs_url="/api/docs", openapi_url="/api/openapi.json")


@app.exception_handler(AdminRequired)
async def _admin_required(request: Request, exc: AdminRequired):
    if request.url.path.startswith("/api/"):
        return JSONResponse({"detail": "운영진 로그인이 필요합니다."}, status_code=401)
    return RedirectResponse(f"/admin/login?next={request.url.path}", status_code=303)


@app.exception_handler(PinChangeRequired)
async def _pin_change(request: Request, exc: PinChangeRequired):
    return RedirectResponse("/pin?next=/admin", status_code=303)


@app.exception_handler(OpError)
async def _op_error(request: Request, exc: OpError):
    return JSONResponse({"detail": str(exc)}, status_code=400)


PUBLIC_DIR = Path(__file__).resolve().parent.parent / "public"


@app.get("/favicon.svg", include_in_schema=False)
def favicon():
    # Vercel에서는 public/ 이 정적으로 먼저 서빙되고, 로컬 개발에서는 이 라우트가 응답한다
    return FileResponse(PUBLIC_DIR / "favicon.svg", media_type="image/svg+xml")


@app.get("/splash.jpg", include_in_schema=False)
def splash_jpg():
    return FileResponse(PUBLIC_DIR / "splash.jpg", media_type="image/jpeg")


@app.get("/arcade.js", include_in_schema=False)
def arcade_js():
    return FileResponse(PUBLIC_DIR / "arcade.js", media_type="text/javascript")


app.include_router(api.router)
app.include_router(admin.router)
app.include_router(arcade.router)
app.include_router(pages.router)
