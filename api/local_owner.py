from django.conf import settings
from django.contrib.auth.models import User


def get_local_owner() -> User:
    owner, created = User.objects.get_or_create(
        username=settings.LOCAL_OWNER_USERNAME
    )
    if created:
        owner.set_unusable_password()
        owner.save(update_fields=["password"])
    return owner
