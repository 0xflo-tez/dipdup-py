import os
from contextlib import AsyncExitStack
from os.path import dirname
from os.path import join
from unittest import IsolatedAsyncioTestCase
from unittest.mock import MagicMock

import pytest
from testcontainers.core.generic import DbContainer  # type: ignore
from testcontainers.postgres import PostgresContainer  # type: ignore

from dipdup.config import DipDupConfig
from dipdup.config import HasuraConfig
from dipdup.config import PostgresDatabaseConfig
from dipdup.dipdup import DipDup
from dipdup.exceptions import HasuraError
from dipdup.hasura import HasuraGateway
from dipdup.utils.database import tortoise_wrapper

if os.environ.get("CI") == "true":
    pytest.skip("skipping integration tests on CI", allow_module_level=True)


class HasuraTest(IsolatedAsyncioTestCase):
    maxDiff = None

    async def test_configure_hasura(self) -> None:
        config_path = join(dirname(__file__), 'hic_et_nunc.yml')
        config = DipDupConfig.load([config_path])
        config.initialize(skip_imports=True)

        async with AsyncExitStack() as stack:
            postgres_container = PostgresContainer()
            # NOTE: Skip healthcheck
            postgres_container._connect = MagicMock()
            stack.enter_context(postgres_container)
            postgres_container._container.reload()
            postgres_ip = postgres_container._container.attrs['NetworkSettings']['IPAddress']

            config.database = PostgresDatabaseConfig(
                kind='postgres',
                host=postgres_ip,
                port=5432,
                user='test',
                database='test',
                password='test',
            )
            dipdup = DipDup(config)
            await stack.enter_async_context(
                tortoise_wrapper(
                    config.database.connection_string,
                    'demo_hic_et_nunc.models',
                )
            )
            await dipdup._set_up_database(stack)
            await dipdup._set_up_hooks(set())
            await dipdup._initialize_schema()

            hasura_container = DbContainer('hasura/graphql-engine:v2.10.1').with_env(
                'HASURA_GRAPHQL_DATABASE_URL',
                f'postgres://test:test@{postgres_ip}:5432',
            )
            hasura_container._connect = MagicMock()
            hasura_container._configure = MagicMock()
            stack.enter_context(hasura_container)
            hasura_container._container.reload()
            hasura_ip = hasura_container._container.attrs['NetworkSettings']['IPAddress']

            config.hasura = HasuraConfig(
                url=f'http://{hasura_ip}:8080',
                source='new_source',
                create_source=True,
            )
            hasura_gateway = HasuraGateway('demo_hic_et_nunc', config.hasura, config.database)
            await stack.enter_async_context(hasura_gateway)

            try:
                await hasura_gateway.configure(force=True)

                config.hasura.camel_case = True

                await hasura_gateway.configure(force=True)
            except HasuraError:
                dipdup._ctx.logger.info(hasura_container.get_logs())
                raise
