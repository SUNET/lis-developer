"""
Airflow DAGs for syncing hosts from Hittade to CISO Assistant.

Three separate DAGs with different schedules:
- cisoass_fetch_hosts: Fetches hosts from Hittade every hour
- cisoass_fetch_domains: Fetches domains from CISO Assistant every 5 minutes,
  triggers sync if domains changed
- cisoass_sync_hosts: Syncs hosts to CISO Assistant (triggered or manual)
"""

import hashlib
import json
import logging
from datetime import datetime, timedelta
from typing import Any

from airflow import DAG
from airflow.sdk import Variable, Connection
from airflow.sdk.bases.hook import BaseHook
from airflow.providers.standard.operators.python import PythonOperator, ShortCircuitOperator
from airflow.providers.standard.operators.trigger_dagrun import TriggerDagRunOperator

from cisoass_add_hosts import (
    get_hittade_client,
    get_ciso_client,
    get_hittade_hosts,
    compile_hittade_services,
    get_current_domains,
    get_current_assets,
    sync_hosts,
    Host,
    Domain,
    Asset,
)

logger = logging.getLogger(__name__)

log_level = Variable.get("log_level", default="INFO")
logger.setLevel(getattr(logging, log_level))

logging.getLogger("ciso_assistant_client").setLevel(getattr(logging, log_level))
logging.getLogger("hittade_client").setLevel(getattr(logging, log_level))

default_args = {
    "owner": "airflow",
    "depends_on_past": False,
    "retries": 1,
    "retry_delay": timedelta(minutes=5),
}

# Connection IDs
CONN_CISO = "ciso_assistant"
CONN_HITTADE = "hittade"

# Variable keys for storing results
VAR_HOSTS = "cisoass_hosts"
VAR_SERVICES = "cisoass_services"
VAR_DOMAINS = "cisoass_domains"
VAR_DOMAINS_HASH = "cisoass_domains_hash"
VAR_ASSETS = "cisoass_assets"


def _conn_to_uri(conn: Connection) -> str:
    base_url = f"{conn.schema}://{conn.host}" if conn.schema else f"{conn.host}"
    if conn.port:
        base_url += f":{conn.port}"
    return base_url


def _extra_from_conn(conn: Connection) -> dict[str, Any]:
    """Parse extra JSON"""
    return json.loads(conn.extra) if conn.extra else {}


def _get_ciso_client_from_conn():
    """Create CISO Assistant client from Airflow connection."""
    conn = BaseHook.get_connection(CONN_CISO)
    base_url = _conn_to_uri(conn)
    extra = _extra_from_conn(conn)
    verify_tls = extra.get("verify_tls", True)
    logger.debug(f"CISO Assistant base url: {base_url}")
    return get_ciso_client(base_url=base_url, token=conn.password, verify_tls=verify_tls)


def _get_hittade_client_from_conn():
    """Create Hittade client from Airflow connection."""
    conn = BaseHook.get_connection(CONN_HITTADE)
    base_url = _conn_to_uri(conn)
    extra = _extra_from_conn(conn)
    verify_tls = extra.get("verify_tls", True)
    logger.debug(f"Hittade server base url: {base_url}")
    return get_hittade_client(base_url=base_url, username=conn.login, password=conn.password, verify_tls=verify_tls)


def _serialize_hosts(hosts: dict[str, Host]) -> str:
    """Serialize hosts dict to JSON for Variable storage."""
    return json.dumps(
        {
            hostname: {
                "id": host.id,
                "name": host.name,
                "config": host.config,
            }
            for hostname, host in hosts.items()
        }
    )


def _deserialize_hosts(data: str) -> dict[str, Host]:
    """Deserialize hosts dict from JSON."""
    parsed = json.loads(data)
    return {hostname: Host.from_obj(h) for hostname, h in parsed.items()}


def _serialize_domains(domains: dict[str, Domain]) -> str:
    """Serialize domains dict to JSON for Variable storage."""
    return json.dumps({name: {"id": d.id, "name": d.name} for name, d in domains.items()})


def _deserialize_domains(data: str) -> dict[str, Domain]:
    """Deserialize domains dict from JSON."""
    parsed = json.loads(data)
    return {name: Domain.from_obj(d) for name, d in parsed.items()}


def _serialize_assets(assets: dict[tuple[str, str], Asset]) -> str:
    """Serialize assets dict to JSON for Variable storage."""
    return json.dumps(
        {
            f"{folder_id}|{name}": {
                "id": a.id,
                "name": a.name,
                "domain_id": a.domain.id if a.domain else None,
                "domain_name": a.domain.name if a.domain else None,
                "parent_assets": [{"id": p.id, "name": p.name} for p in a.parent_assets],
            }
            for (folder_id, name), a in assets.items()
        }
    )


def _deserialize_assets(data: str) -> dict[tuple[str, str], Asset]:
    """Deserialize assets dict from JSON."""
    parsed = json.loads(data)
    result = {}
    for key, a in parsed.items():
        folder_id, name = key.split("|", 1)
        result[(folder_id, name)] = Asset.from_obj(a)
    return result


def task_get_hittade_hosts(**context):
    """Fetch hosts from Hittade and store in Airflow Variable."""
    import asyncio

    client = _get_hittade_client_from_conn()
    hosts = asyncio.run(get_hittade_hosts(client=client))
    Variable.set(VAR_HOSTS, _serialize_hosts(hosts))
    logger.info(f"Retrieved {len(hosts)} hosts from Hittade")


def task_compile_services(**context):
    """Compile services from hosts and store in Airflow Variable."""
    hosts_data = Variable.get(VAR_HOSTS)
    hosts = _deserialize_hosts(hosts_data)
    services = compile_hittade_services(hosts)
    Variable.set(VAR_SERVICES, json.dumps(services))
    logger.info(f"Compiled {len(services)} services")


def task_get_current_domains(**context):
    """Fetch current domains from CISO Assistant and store in Airflow Variable."""
    import asyncio

    client = _get_ciso_client_from_conn()
    domains = asyncio.run(get_current_domains(client=client))
    serialized = _serialize_domains(domains)
    Variable.set(VAR_DOMAINS, serialized)
    # Store hash for change detection
    new_hash = hashlib.md5(serialized.encode()).hexdigest()
    context["ti"].xcom_push(key="domains_hash", value=new_hash)
    logger.info(f"Retrieved {len(domains)} domains from CISO Assistant")


def task_check_domains_changed(**context):
    """Check if domains have changed since last run. Returns True if changed."""
    new_hash = context["ti"].xcom_pull(task_ids="get_current_domains", key="domains_hash")
    old_hash = Variable.get(VAR_DOMAINS_HASH, default=None)

    if new_hash != old_hash:
        Variable.set(VAR_DOMAINS_HASH, new_hash)
        logger.info("Domains have changed, triggering sync")
        return True
    logger.info("Domains unchanged, skipping sync")
    return False


def task_get_current_assets(**context):
    """Fetch current assets from CISO Assistant and store in Airflow Variable."""
    import asyncio

    client = _get_ciso_client_from_conn()
    assets = asyncio.run(get_current_assets(client=client))
    Variable.set(VAR_ASSETS, _serialize_assets(assets))
    logger.info(f"Retrieved {len(assets)} assets from CISO Assistant")


def task_sync_hosts(**context):
    """Sync hosts from Hittade to CISO Assistant using stored Variables."""
    import asyncio

    services = json.loads(Variable.get(VAR_SERVICES))
    domains = _deserialize_domains(Variable.get(VAR_DOMAINS))
    assets = _deserialize_assets(Variable.get(VAR_ASSETS))

    client = _get_ciso_client_from_conn()
    asyncio.run(sync_hosts(client=client, services=services, domains=domains, assets=assets))
    logger.info("Hosts have been synced to CISO Assistant")


# DAG 1: Fetch hosts from Hittade every hour
with DAG(
    dag_id="cisoass_fetch_hosts",
    default_args=default_args,
    description="Fetch hosts from Hittade every hour",
    schedule="0 * * * *",  # Every hour
    start_date=datetime(2025, 12, 11),
    catchup=False,
    tags=["hittade"],
) as dag_fetch_hosts:
    get_hosts = PythonOperator(
        task_id="get_hittade_hosts",
        python_callable=task_get_hittade_hosts,
    )

    compile_services = PythonOperator(
        task_id="compile_services",
        python_callable=task_compile_services,
    )

    trigger_sync = TriggerDagRunOperator(
        task_id="trigger_sync",
        trigger_dag_id="cisoass_sync_hosts",
    )

    get_hosts >> compile_services >> trigger_sync


# DAG 2: Fetch domains from CISO Assistant every 5 minutes, trigger sync if changed
with DAG(
    dag_id="cisoass_fetch_domains",
    default_args=default_args,
    description="Fetch domains from CISO Assistant every 5 minutes",
    schedule="*/5 * * * *",  # Every 5 minutes
    start_date=datetime(2025, 12, 11),
    catchup=False,
    tags=["ciso"],
) as dag_fetch_domains:
    get_domains = PythonOperator(
        task_id="get_current_domains",
        python_callable=task_get_current_domains,
    )

    check_changed = ShortCircuitOperator(
        task_id="check_domains_changed",
        python_callable=task_check_domains_changed,
    )

    trigger_sync = TriggerDagRunOperator(
        task_id="trigger_sync",
        trigger_dag_id="cisoass_sync_hosts",
    )

    get_domains >> check_changed >> trigger_sync


# DAG 3: Sync hosts to CISO Assistant (triggered by domain changes or fetch hosts task)
with DAG(
    dag_id="cisoass_sync_hosts",
    default_args=default_args,
    description="Sync hosts to CISO Assistant",
    schedule=None,  # Only triggered
    start_date=datetime(2025, 12, 11),
    catchup=False,
    tags=["ciso", "hittade", "sync"],
) as dag_sync:
    get_assets = PythonOperator(
        task_id="get_current_assets",
        python_callable=task_get_current_assets,
    )

    sync = PythonOperator(
        task_id="sync_hosts",
        python_callable=task_sync_hosts,
    )

    get_assets >> sync
