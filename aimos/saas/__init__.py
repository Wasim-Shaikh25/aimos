"""SaaS layer: user registration/login, multi-tenancy, and tenant-scoped resources.

Uses only free/open-source dependencies. External services (SMTP, OAuth, SMS)
are operator-supplied and configured in ``config/saas.yaml`` or via
``AIMOS__SAAS__*`` env overrides.
"""

from aimos.saas.settings import SaasConfig, get_saas_config

__all__ = ["SaasConfig", "get_saas_config"]
