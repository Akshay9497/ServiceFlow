import os
from datetime import timedelta
from pathlib import Path

from dotenv import load_dotenv
from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def env_bool(name, default=False):
    value = os.environ.get(name)
    if value is None:
        return default
    normalized = value.lower()
    if normalized in {"1", "true", "yes"}:
        return True
    if normalized in {"0", "false", "no"}:
        return False
    raise ImproperlyConfigured(f"{name} must be set to a boolean value.")


SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY")
if not SECRET_KEY or SECRET_KEY.startswith("replace-with-"):
    raise ImproperlyConfigured(
        "Set DJANGO_SECRET_KEY to a new random secret in the backend environment."
    )

DEBUG = env_bool("DJANGO_DEBUG")
PUBLIC_REGISTRATION_ENABLED = env_bool("PUBLIC_REGISTRATION_ENABLED", DEBUG)
ALLOWED_HOSTS = [
    host.strip()
    for host in os.environ.get("DJANGO_ALLOWED_HOSTS", "127.0.0.1,localhost").split(",")
    if host.strip()
]
SECURE_SSL_REDIRECT = env_bool("DJANGO_SECURE_SSL_REDIRECT")
SESSION_COOKIE_SECURE = env_bool("DJANGO_SESSION_COOKIE_SECURE")
CSRF_COOKIE_SECURE = env_bool("DJANGO_CSRF_COOKIE_SECURE")
SECURE_HSTS_SECONDS = int(os.environ.get("DJANGO_SECURE_HSTS_SECONDS", "0"))
SECURE_HSTS_INCLUDE_SUBDOMAINS = env_bool(
    "DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS"
)
SECURE_HSTS_PRELOAD = env_bool("DJANGO_SECURE_HSTS_PRELOAD")
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"
SECURE_PROXY_SSL_HEADER = (
    ("HTTP_X_FORWARDED_PROTO", "https")
    if env_bool("DJANGO_TRUST_PROXY_SSL_HEADER")
    else None
)
DRF_NUM_PROXIES = int(os.environ.get("DRF_NUM_PROXIES", "0"))
if DRF_NUM_PROXIES < 0:
    raise ImproperlyConfigured("DRF_NUM_PROXIES cannot be negative.")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "corsheaders",
    "rest_framework",
    "rest_framework_simplejwt.token_blacklist",
    "api",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ.get("PGDATABASE", "serviceflow"),
        "USER": os.environ.get("PGUSER", "serviceflow"),
        "PASSWORD": os.environ.get("PGPASSWORD", ""),
        "HOST": os.environ.get("PGHOST", "localhost"),
        "PORT": os.environ.get("PGPORT", "5432"),
        "CONN_MAX_AGE": 60,
        **(
            {
                "OPTIONS": {
                    **(
                        {"sslmode": os.environ["PGSSLMODE"]}
                        if os.environ.get("PGSSLMODE")
                        else {}
                    ),
                    **(
                        {"sslrootcert": os.environ["PGSSLROOTCERT"]}
                        if os.environ.get("PGSSLROOTCERT")
                        else {}
                    ),
                }
            }
            if os.environ.get("PGSSLMODE") or os.environ.get("PGSSLROOTCERT")
            else {}
        ),
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]

LANGUAGE_CODE = "en-in"
TIME_ZONE = "Asia/Kolkata"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

CORS_ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.environ.get(
        "CORS_ALLOWED_ORIGINS", "http://localhost:5173"
    ).split(",")
    if origin.strip()
]
CSRF_TRUSTED_ORIGINS = [
    origin.strip()
    for origin in os.environ.get("DJANGO_CSRF_TRUSTED_ORIGINS", "").split(",")
    if origin.strip()
]

REST_FRAMEWORK = {
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework_simplejwt.authentication.JWTAuthentication",
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_RENDERER_CLASSES": (
        ["rest_framework.renderers.JSONRenderer"]
        + (
            ["rest_framework.renderers.BrowsableAPIRenderer"]
            if DEBUG and env_bool("DRF_BROWSABLE_API_ENABLED", True)
            else []
        )
    ),
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 50,
    "DEFAULT_THROTTLE_RATES": {
        "auth_register": os.environ.get("AUTH_REGISTER_RATE", "5/hour"),
        "auth_token": os.environ.get("AUTH_TOKEN_RATE", "10/minute"),
        "auth_refresh": os.environ.get("AUTH_REFRESH_RATE", "30/minute"),
        "auth_password_reset": os.environ.get("AUTH_PASSWORD_RESET_RATE", "5/hour"),
        "auth_password_reset_otp": os.environ.get(
            "AUTH_PASSWORD_RESET_OTP_RATE", "10/minute"
        ),
        "organization_create": os.environ.get("ORGANIZATION_CREATE_RATE", "5/hour"),
    },
    "NUM_PROXIES": DRF_NUM_PROXIES,
}

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=20),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=1),
    "AUTH_HEADER_TYPES": ("Bearer",),
}

EMAIL_BACKEND = os.environ.get(
    "EMAIL_BACKEND", "django.core.mail.backends.console.EmailBackend"
)
EMAIL_HOST = os.environ.get("EMAIL_HOST", "localhost")
EMAIL_PORT = int(os.environ.get("EMAIL_PORT", "25"))
EMAIL_HOST_USER = os.environ.get("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.environ.get("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = os.environ.get("EMAIL_USE_TLS", "false").lower() in {
    "1",
    "true",
    "yes",
}
DEFAULT_FROM_EMAIL = os.environ.get(
    "DEFAULT_FROM_EMAIL", "ServiceFlow <no-reply@localhost>"
)
PASSWORD_RESET_OTP_TIMEOUT = 10 * 60
PASSWORD_RESET_VERIFICATION_TIMEOUT = 10 * 60
PASSWORD_RESET_OTP_MAX_ATTEMPTS = 5

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "serviceflow": {
            "format": "{asctime} {levelname} {name} {message}",
            "style": "{",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "serviceflow",
        },
    },
    "loggers": {
        "django.request": {"handlers": ["console"], "level": "WARNING"},
        "django.security": {"handlers": ["console"], "level": "WARNING"},
        "api": {"handlers": ["console"], "level": "INFO"},
    },
}
