"""
Custom decorators for permission checking.

Usage:
    @permission_required('users.create')
    def my_view(): ...

    @admin_required
    def admin_only_view(): ...
"""
from functools import wraps
from flask import abort, redirect, url_for
from flask_login import current_user


def permission_required(permission: str):
    """Abort 403 unless the current user has the named permission."""
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            if not current_user.is_authenticated:
                return redirect(url_for("auth.login"))
            if not current_user.has_permission(permission):
                abort(403)
            return f(*args, **kwargs)
        return decorated
    return decorator


def admin_required(f):
    """Abort 403 unless current user is_admin == True."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for("auth.login"))
        if not current_user.is_admin:
            abort(403)
        return f(*args, **kwargs)
    return decorated
