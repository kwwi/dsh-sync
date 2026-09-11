import os

import pytest

os.environ["LLM_MOCK"] = "true"
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["PYTEST_CURRENT_TEST"] = "1"


@pytest.fixture(autouse=True)
def _reset_settings_cache():
    from app.config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
async def setup_db():
    import app.db.session as db_session
    from app.corpus.search import seed_corpus_if_empty
    from app.db.session import init_db, get_session_factory

    db_session._engine = None
    db_session._session_factory = None
    await init_db()
    # 为测试环境种子语料和五行数据
    async with get_session_factory()() as session:
        await seed_corpus_if_empty(session)
    yield
    db_session._engine = None
    db_session._session_factory = None
