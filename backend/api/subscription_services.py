from rest_framework.exceptions import ValidationError

from api.models import (
    Customer,
    Equipment,
    Membership,
    OrganizationSubscription,
    ServiceJob,
)


USAGE_LIMITS = {
    "members": ("max_members", Membership),
    "customers": ("max_customers", Customer),
    "equipment": ("max_equipment", Equipment),
    "jobs": ("max_jobs", ServiceJob),
}


def usage_for(organization, resource):
    limit_field, model = USAGE_LIMITS[resource]
    subscription = (
        OrganizationSubscription.objects.filter(organization=organization)
        .select_related("plan")
        .first()
    )
    limit = getattr(subscription.plan, limit_field) if subscription else None
    current = model.objects.filter(organization=organization).count()
    return {"used": current, "limit": limit, "unlimited": limit is None}


def enforce_usage_limit(organization, resource):
    usage = usage_for(organization, resource)
    if usage["limit"] is not None and usage["used"] >= usage["limit"]:
        raise ValidationError(
            {
                "detail": (
                    f"The current plan limit of {usage['limit']} "
                    f"{resource} has been reached."
                ),
                "resource": resource,
                "used": usage["used"],
                "limit": usage["limit"],
            }
        )
