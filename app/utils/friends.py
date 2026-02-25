"""
Friend-group permission helpers.

Rules:
  - Admin users can view any Box.
  - Regular users can view a Box if they share at least one FriendGroup with the owner.
  - Transfers are only allowed from a Box row (not from a deck), between different users
    who share a group.
"""
from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.models.user import User
    from app.models.inventory import Inventory


def can_view_box(viewer: "User", target_user: "User") -> bool:
    """Return True if viewer is allowed to see target_user's Box."""
    if viewer.id == target_user.id:
        return True
    if viewer.is_admin or viewer.has_permission("admin.full_access"):
        return True
    return viewer.shares_group_with(target_user)


def can_transfer_card(actor: "User", inventory_item: "Inventory") -> bool:
    """Return True if actor may take inventory_item from its owner's Box.

    Conditions:
      - The inventory row must be in the Box (not in a deck).
      - actor and the owner must be in the same FriendGroup.
      - actor cannot take their own cards (use move_card instead).
    """
    if inventory_item.current_deck_id is not None:
        return False   # Only Box cards can be transferred
    owner = inventory_item.user
    if actor.id == owner.id:
        return False   # Can't "take" your own card
    return can_view_box(actor, owner)


def get_friend_group_members(user: "User") -> list["User"]:
    """Return a deduplicated, alphabetically sorted list of users who share
    at least one FriendGroup with *user*, excluding *user* themselves.
    """
    seen_ids: set[int] = {user.id}
    members: list["User"] = []
    for group in user.friend_groups:
        for member in group.members:
            if member.id not in seen_ids:
                seen_ids.add(member.id)
                members.append(member)
    return sorted(members, key=lambda u: u.username.lower())
