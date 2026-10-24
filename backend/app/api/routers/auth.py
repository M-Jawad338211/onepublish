from fastapi import APIRouter, HTTPException, Request, Response, status

from app.api.deps import (
    SettingsDep,
    clear_session_cookie,
    client_key,
    is_authenticated,
    login_limiter,
    set_session_cookie,
    verify_password,
)
from app.schemas import LoginIn, Me

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=Me)
async def login(body: LoginIn, request: Request, response: Response, settings: SettingsDep) -> Me:
    key = client_key(request)
    if login_limiter.blocked(key):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many attempts; try later")
    if not verify_password(settings, body.password):
        login_limiter.fail(key)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Wrong password")
    login_limiter.reset(key)
    set_session_cookie(response, settings)
    return Me(authenticated=True)


@router.post("/logout", response_model=Me)
async def logout(response: Response) -> Me:
    clear_session_cookie(response)
    return Me(authenticated=False)


@router.get("/me", response_model=Me)
async def me(request: Request, settings: SettingsDep) -> Me:
    return Me(authenticated=is_authenticated(request, settings))
