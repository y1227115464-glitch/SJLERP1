from alembic import context

from app.core.config import Settings
from app.core.database import Database
from app.models import Base

target_metadata = Base.metadata
settings = Settings()

if context.is_offline_mode():
    context.configure(url=settings.database_url, target_metadata=target_metadata, literal_binds=True, dialect_opts={"paramstyle": "named"})
    with context.begin_transaction():
        context.run_migrations()
else:
    database = Database(settings)
    with database.engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()
