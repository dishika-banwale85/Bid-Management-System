from fastapi import FastAPI,Request,HTTPException
from contextlib import asynccontextmanager
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from zoneinfo import ZoneInfo
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.encoders import jsonable_encoder
from app.core.config import FRONTEND_ORIGIN
from app.models import *  # noqa: F401,F403 - register ORM metadata
from app.api import auth,bids,requests as requests_api,notifications,approvals,contacts,dashboard,reports,reminders,admin

_scheduler=BackgroundScheduler(timezone=ZoneInfo("Asia/Kolkata"))
def _safe_reminder_job():
    try:
        from app.services.reminder_service import run_reminders
        run_reminders()
    except Exception:
        # Scheduler errors are isolated from the API process; inspect app logs for details.
        import logging;logging.getLogger("bidease.reminders").exception("Daily reminder run failed")
@asynccontextmanager
async def lifespan(app):
    _scheduler.add_job(_safe_reminder_job,CronTrigger(hour=9,minute=0,timezone=ZoneInfo("Asia/Kolkata")),id="daily-reminders",replace_existing=True)
    _scheduler.start()
    try:yield
    finally:_scheduler.shutdown(wait=False)
app=FastAPI(title="BidEase API",version="0.3.0",lifespan=lifespan)
frontend_origins={FRONTEND_ORIGIN.rstrip("/")}
if FRONTEND_ORIGIN.rstrip("/") in {"http://localhost:5173","http://127.0.0.1:5173"}:
    frontend_origins.update({"http://localhost:5173","http://127.0.0.1:5173"})
app.add_middleware(CORSMiddleware,allow_origins=sorted(frontend_origins),allow_credentials=True,allow_methods=["GET","POST","PUT","PATCH","DELETE","OPTIONS"],allow_headers=["Authorization","Content-Type"])
@app.exception_handler(RequestValidationError)
async def validation_error(request:Request,exc:RequestValidationError):
    return JSONResponse(status_code=422,content=jsonable_encoder({"error":"validation_error","message":"Request validation failed","fields":exc.errors()}))
@app.exception_handler(HTTPException)
async def http_error(request:Request,exc:HTTPException):
    payload=exc.detail if isinstance(exc.detail,dict) else {"error":"request_error","message":str(exc.detail)}
    return JSONResponse(status_code=exc.status_code,content=jsonable_encoder(payload),headers=exc.headers)
app.include_router(auth.router);app.include_router(bids.router);app.include_router(requests_api.router);app.include_router(notifications.router);app.include_router(approvals.router);app.include_router(contacts.router);app.include_router(dashboard.router);app.include_router(reports.router);app.include_router(reminders.router);app.include_router(admin.router)
@app.get("/health")
def health():return {"status":"ok"}
