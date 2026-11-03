"""Shared role policy for API dependencies, services and background workers."""

SUPER_ADMIN_EMAIL = "alisan.yildirim@fbu.edu.tr"


def is_super_admin(user):
    return bool(user and user.role == "super_admin" and user.email.casefold() == SUPER_ADMIN_EMAIL)


def is_admin(user):
    return bool(user and (user.role == "admin" or is_super_admin(user)))


def can_operate(user):
    return bool(user and (user.role == "operator" or is_admin(user)))


def can_ssh(user):
    return bool(user and (is_super_admin(user) or user.ssh_access))
