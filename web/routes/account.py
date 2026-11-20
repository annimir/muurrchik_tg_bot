from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse

from database.queries import get_user_by_tg_id
from database.tierlists import attach_tier_list_previews, list_user_tier_lists
from database.wish_rewards import (
    get_wish_reward_progress, get_wish_reward_summary, list_wish_reward_grants,
)
from database.wishes import (
    get_or_create_current_wish_event, get_participant, get_recent_drops,
)
from web.auth import (
    SESSION_COOKIE, csrf_protect, read_admin_session, require_user,
)
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
    event = get_or_create_current_wish_event()
    participant = get_participant(event['id'], user['id'])
    reward_rules = get_wish_reward_progress(event['id'], user['id'])
    tier_lists = attach_tier_list_previews(list_user_tier_lists(user['id'])[:3])
    return templates.TemplateResponse(
        request=request,
        name='account.html',
        context={
            'user': user,
            'event': event,
            'participant': participant,
            'reward_rules': reward_rules,
            'reward_summary': get_wish_reward_summary(event['id'], user['id']),
            'reward_grants': list_wish_reward_grants(event['id'], user['id'], limit=5),
            'recent_drops': get_recent_drops(event['id'], user['id'], limit=8),
            'tier_lists': tier_lists,
            'earned_levels': sum(rule['level'] for rule in reward_rules),
            'max_levels': len(reward_rules) * 3,
            'csrf_token': session['csrf'],
            'active_page': 'account',
        },
    )


@router.post('/account/logout', name='account_logout')
async def account_logout(_=Depends(require_user), __=Depends(csrf_protect)):
    response = RedirectResponse('/', status_code=303)
    response.delete_cookie(SESSION_COOKIE, path='/')
    return response
