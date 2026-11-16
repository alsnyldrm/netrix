"""Shared role policy for API dependencies, services and background workers."""

SUPER_ADMIN_EMAIL = "alisan.yildirim@fbu.edu.tr"


def is_recovery_owner(user):
    return bool(
        user
        and getattr(user, "auth_source", "local") == "local"
        and user.email.casefold() == SUPER_ADMIN_EMAIL
    )


def is_super_admin(user):
    return bool(user and user.role == "super_admin")


def is_admin(user):
    return bool(user and (user.role == "admin" or is_super_admin(user)))


def can_operate(user):
    return bool(user and (user.role == "operator" or is_admin(user)))


def can_ssh(user):
    return bool(user and (is_super_admin(user) or user.ssh_access))
