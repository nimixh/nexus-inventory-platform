from app.models.user import User


def test_user_role_enum_persists_lowercase_values():
    """SQLAlchemy enum mapping must match PostgreSQL enum literals."""
    role_enum = User.__table__.c.role.type
    assert role_enum.enums == ["owner", "admin", "ops", "viewer"]
    assert role_enum.validate_strings is True
