from django.urls import path
from rest_framework.routers import SimpleRouter

from api.views import (
    CurrentUserView,
    CustomerViewSet,
    EmailTokenObtainPairView,
    EmailTokenRefreshView,
    EquipmentViewSet,
    HealthCheckView,
    LogoutView,
    MembershipViewSet,
    OrganizationListView,
    PasswordResetCompleteView,
    PasswordResetEmailChangeView,
    PasswordResetOTPVerifyView,
    PasswordResetRequestView,
    PublicConfigurationView,
    RegistrationView,
    ServiceJobViewSet,
    ServiceContractViewSet,
)
from api.finance_views import (
    CashBankTransferViewSet,
    ExpenseViewSet,
    FinancialAuditEventViewSet,
    FinancialReportViewSet,
    InvoiceViewSet,
    JournalEntryViewSet,
    PaymentViewSet,
    QuotationViewSet,
)
from api.subscription_views import (
    OrganizationSubscriptionInvoiceListView,
    OrganizationSubscriptionView,
    PlatformSubscriptionInvoicePaymentView,
    PlatformSubscriptionRequestDecisionView,
    PlatformSubscriptionRequestListView,
    SubscriptionPlansView,
)

router = SimpleRouter()
router.register(
    r"organizations/(?P<organization_pk>\d+)/customers",
    CustomerViewSet,
    basename="organization-customer",
)
router.register(
    r"organizations/(?P<organization_pk>\d+)/members",
    MembershipViewSet,
    basename="organization-member",
)
router.register(
    r"organizations/(?P<organization_pk>\d+)/equipment",
    EquipmentViewSet,
    basename="organization-equipment",
)
router.register(
    r"organizations/(?P<organization_pk>\d+)/jobs",
    ServiceJobViewSet,
    basename="organization-job",
)
router.register(
    r"organizations/(?P<organization_pk>\d+)/contracts",
    ServiceContractViewSet,
    basename="organization-contract",
)
router.register(
    r"organizations/(?P<organization_pk>\d+)/invoices",
    InvoiceViewSet,
    basename="organization-invoice",
)
router.register(
    r"organizations/(?P<organization_pk>\d+)/quotations",
    QuotationViewSet,
    basename="organization-quotation",
)
router.register(
    r"organizations/(?P<organization_pk>\d+)/payments",
    PaymentViewSet,
    basename="organization-payment",
)
router.register(
    r"organizations/(?P<organization_pk>\d+)/expenses",
    ExpenseViewSet,
    basename="organization-expense",
)
router.register(
    r"organizations/(?P<organization_pk>\d+)/cash-bank-transfers",
    CashBankTransferViewSet,
    basename="organization-cash-bank-transfer",
)
router.register(
    r"organizations/(?P<organization_pk>\d+)/journals",
    JournalEntryViewSet,
    basename="organization-journal",
)
router.register(
    r"organizations/(?P<organization_pk>\d+)/financial-audit",
    FinancialAuditEventViewSet,
    basename="organization-financial-audit",
)
router.register(
    r"organizations/(?P<organization_pk>\d+)/reports",
    FinancialReportViewSet,
    basename="organization-financial-report",
)

urlpatterns = [
    path("health/", HealthCheckView.as_view(), name="health-check"),
    path("public-config/", PublicConfigurationView.as_view(), name="public-config"),
    path("auth/register/", RegistrationView.as_view(), name="register"),
    path("auth/token/", EmailTokenObtainPairView.as_view(), name="token-obtain-pair"),
    path("auth/token/refresh/", EmailTokenRefreshView.as_view(), name="token-refresh"),
    path(
        "auth/password-reset/",
        PasswordResetRequestView.as_view(),
        name="password-reset-request",
    ),
    path(
        "auth/password-reset/verify/",
        PasswordResetOTPVerifyView.as_view(),
        name="password-reset-verify",
    ),
    path(
        "auth/password-reset/new-email/",
        PasswordResetEmailChangeView.as_view(),
        name="password-reset-new-email",
    ),
    path(
        "auth/password-reset/complete/",
        PasswordResetCompleteView.as_view(),
        name="password-reset-complete",
    ),
    path("auth/logout/", LogoutView.as_view(), name="logout"),
    path("auth/me/", CurrentUserView.as_view(), name="current-user"),
    path("subscription/plans/", SubscriptionPlansView.as_view(), name="subscription-plans"),
    path(
        "platform/subscription-requests/",
        PlatformSubscriptionRequestListView.as_view(),
        name="platform-subscription-requests",
    ),
    path(
        "platform/subscription-requests/<int:request_id>/decision/",
        PlatformSubscriptionRequestDecisionView.as_view(),
        name="platform-subscription-request-decision",
    ),
    path(
        "platform/subscription-invoices/<int:invoice_id>/mark-paid/",
        PlatformSubscriptionInvoicePaymentView.as_view(),
        name="platform-subscription-invoice-mark-paid",
    ),
    path("organizations/", OrganizationListView.as_view(), name="organization-list"),
    path(
        "organizations/<int:organization_pk>/subscription/",
        OrganizationSubscriptionView.as_view(),
        name="organization-subscription",
    ),
    path(
        "organizations/<int:organization_pk>/subscription/invoices/",
        OrganizationSubscriptionInvoiceListView.as_view(),
        name="organization-subscription-invoices",
    ),
    *router.urls,
]
