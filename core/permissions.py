from core.users import ROLE_OWNER, User


def is_allowed(user: User | None, action: str) -> bool:
    """The one place that decides who may do what.

    For now only the owner is allowed anything, whatever the action. Roles and
    per-action rules go here when real users arrive.
    """
    return user is not None and user.role == ROLE_OWNER
