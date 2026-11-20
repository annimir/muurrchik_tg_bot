from database.assistance import get_helper_public_summary, list_helper_modes
from database.queries import get_user_titles
from database.tierlists import attach_tier_list_previews, list_user_tier_lists
from database.wish_rewards import (
    get_wish_reward_progress, get_wish_reward_summary, list_wish_reward_grants,
)
from database.wishes import (
    get_or_create_current_wish_event, get_participant, get_recent_drops,
)
from web.queries import (
    get_public_user, get_public_user_characters, get_public_user_games,
    get_public_user_subscriptions,
)


def build_profile_context(user_id, session=None):
    user = get_public_user(user_id)
    if not user:
        return None
    is_owner = bool(session and session['tg_id'] == user['tg_id'])
    context = {
        'user': user,
        'games': get_public_user_games(user_id),
        'titles': get_user_titles(user_id),
        'tier_lists': attach_tier_list_previews(list_user_tier_lists(user_id)),
        'characters': get_public_user_characters(user_id),
        'subscriptions': get_public_user_subscriptions(user_id),
        'helper_profile': get_helper_public_summary(user_id),
        'helper_modes': list_helper_modes(user_id, active_only=True),
        'is_own_profile': is_owner,
    }
    if is_owner:
        event = get_or_create_current_wish_event()
        reward_rules = get_wish_reward_progress(event['id'], user_id)
        context.update({
            'event': event,
            'participant': get_participant(event['id'], user_id),
            'reward_rules': reward_rules,
            'reward_summary': get_wish_reward_summary(event['id'], user_id),
            'reward_grants': list_wish_reward_grants(event['id'], user_id, limit=5),
            'recent_drops': get_recent_drops(event['id'], user_id, limit=8),
            'earned_levels': sum(rule['level'] for rule in reward_rules),
            'max_levels': len(reward_rules) * 3,
            'csrf_token': session['csrf'],
        })
    return context
