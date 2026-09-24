import pytest

import env_guard

PROD_URL = "postgresql://postgres.qodznpcwoppzugoxqord:pw@aws-1-ap-northeast-2.pooler.supabase.com:6543/postgres"


@pytest.fixture()
def env(monkeypatch):
    for k in ("APP_ENV", "DATABASE_URL", "SUPABASE_URL", "ALLOW_PROD_DB"):
        monkeypatch.delenv(k, raising=False)
    return monkeypatch


@pytest.mark.parametrize("app_env", ["local", "test", "staging"])
def test_guarded_envs_refuse_prod_database(env, app_env):
    env.setenv("APP_ENV", app_env)
    env.setenv("DATABASE_URL", PROD_URL)
    with pytest.raises(env_guard.ProductionDatabaseError):
        env_guard.check()


def test_guarded_env_refuses_prod_supabase_rest_url(env):
    env.setenv("APP_ENV", "local")
    env.setenv("SUPABASE_URL", "https://qodznpcwoppzugoxqord.supabase.co")
    with pytest.raises(env_guard.ProductionDatabaseError):
        env_guard.check()


def test_production_is_not_guarded(env):
    env.setenv("DATABASE_URL", PROD_URL)      # APP_ENV unset == production
    env_guard.check()


def test_local_sqlite_is_fine(env):
    env.setenv("APP_ENV", "local")
    env.setenv("DATABASE_URL", "")
    env_guard.check()


def test_staging_project_is_fine(env):
    env.setenv("APP_ENV", "staging")
    env.setenv("DATABASE_URL", PROD_URL.replace("qodznpcwoppzugoxqord", "stagingref123"))
    env_guard.check()


def test_explicit_override(env):
    env.setenv("APP_ENV", "local")
    env.setenv("DATABASE_URL", PROD_URL)
    env.setenv("ALLOW_PROD_DB", "1")
    env_guard.check()
