from rest_framework.permissions import BasePermission

from api.models import Membership, ServiceJob


class OrganizationRolePermission(BasePermission):
    message = "Your organization role does not allow this action."

    write_roles = {
        Membership.Role.OWNER,
        Membership.Role.ADMIN,
        Membership.Role.MANAGER,
    }

    def has_permission(self, request, view):
        if not request.user.is_authenticated:
            return False

        organization_id = view.kwargs.get("organization_pk")
        if organization_id is None:
            return False

        membership = Membership.objects.filter(
            organization_id=organization_id, user=request.user
        ).first()
        if membership is None:
            return False

        view.organization_membership = membership
        if request.method in {"GET", "HEAD", "OPTIONS"}:
            return True
        return membership.role in self.write_roles


class FinancialRolePermission(BasePermission):
    message = "Only owners, administrators, and managers can access financial records."

    allowed_roles = {
        Membership.Role.OWNER,
        Membership.Role.ADMIN,
        Membership.Role.MANAGER,
    }

    def has_permission(self, request, view):
        if not request.user.is_authenticated:
            return False
        membership = Membership.objects.filter(
            organization_id=view.kwargs.get("organization_pk"),
            user=request.user,
        ).first()
        if membership is None or membership.role not in self.allowed_roles:
            return False
        view.organization_membership = membership
        return True


class MembershipManagementPermission(BasePermission):
    message = "Only organization owners and administrators can manage memberships."

    def has_permission(self, request, view):
        if not request.user.is_authenticated:
            return False

        membership = Membership.objects.filter(
            organization_id=view.kwargs.get("organization_pk"), user=request.user
        ).first()
        if membership is None:
            return False
        view.organization_membership = membership
        if membership.role == Membership.Role.MANAGER:
            return request.method in {"GET", "HEAD", "OPTIONS"}
        if membership.role not in {Membership.Role.OWNER, Membership.Role.ADMIN}:
            return False

        return True

    def has_object_permission(self, request, view, obj):
        if obj.role != Membership.Role.OWNER:
            return True

        if request.user == obj.user:
            return False

        return Membership.objects.filter(
            organization=obj.organization, role=Membership.Role.OWNER
        ).exclude(pk=obj.pk).exists()


class ServiceJobPermission(BasePermission):
    message = "Your organization role does not allow this service job action."

    staff_roles = {
        Membership.Role.OWNER,
        Membership.Role.ADMIN,
        Membership.Role.MANAGER,
    }

    technician_update_fields = {"status", "technician_note", "completion_report"}

    def has_permission(self, request, view):
        if not request.user.is_authenticated:
            return False

        membership = Membership.objects.filter(
            organization_id=view.kwargs.get("organization_pk"), user=request.user
        ).first()
        if membership is None:
            return False

        view.organization_membership = membership
        if request.method in {"GET", "HEAD", "OPTIONS"}:
            return True
        if membership.role in self.staff_roles:
            return True
        return (
            membership.role == Membership.Role.TECHNICIAN
            and (
                request.method == "PATCH"
                or (request.method == "POST" and view.action == "notes")
            )
        )

    def has_object_permission(self, request, view, obj):
        membership = view.organization_membership
        if membership.role in self.staff_roles:
            return True
        if membership.role != Membership.Role.TECHNICIAN:
            return False
        if obj.assigned_technician_id != membership.id:
            return False
        if request.method in {"GET", "HEAD", "OPTIONS"}:
            return True
        if request.method == "POST" and view.action == "notes":
            return True
        if request.method != "PATCH":
            return False
        return set(request.data.keys()).issubset(self.technician_update_fields)
