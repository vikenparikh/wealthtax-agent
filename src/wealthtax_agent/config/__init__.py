"""Configuration package: runtime settings + tax-tables loader.

``settings`` carries env-driven values (DB URL, encryption key, mode, etc.);
``tax_tables`` carries the per-year/per-jurisdiction YAML rate tables.
"""

from wealthtax_agent.config.settings import Settings, get_settings, reset_settings_cache  # noqa: F401
