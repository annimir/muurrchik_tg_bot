from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse

from database.queries import get_user_by_tg_id
from web.auth import SESSION_COOKIE, csrf_protect, read_admin_session, require_user
from web.profile import build_profile_context
from web.rendering import templates

router = APIRouter()


def _account_user(request: Request):
    session = read_admin_session(request)
    if not session:
        raise HTTPException(
            status_code=303, headers={'Location': '/tierlists/login?next=/account'},
        )
    user = get_user_by_tg_id(session['tg_id'])
    if not user:
        raise HTTPException(status_code=404, detail='Игрок не найден')
    return session, user


@router.get('/account', name='account_page')
async def account_page(request: Request):
    session, user = _account_user(request)
    context = build_profile_context(user['id'], session)
    return templates.TemplateResponse(
        request=request,
        name='user_detail.html',
        context={**context, 'active_page': 'account'},
    )


@router.post('/account/logout', name='account_logout')
async def account_logout(_=Depends(require_user), __=Depends(csrf_protect)):
    response = RedirectResponse('/', status_code=303)
    response.delete_cookie(SESSION_COOKIE, path='/')
    return response
