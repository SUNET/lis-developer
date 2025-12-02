import asyncio
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import Self, Any

from ciso_assistant_client import (
    AsyncCISOAssistantClient as CisoClient,
    ApiToken,
    FolderRead,
    AssetRead,
    AssetWrite,
    AsyncCISOAssistantClient,
)
from ciso_assistant_client.models.assets import (
    AssetType,
    AssetWriteResponse,
    Dependency,
)
from ciso_assistant_client.models.folders import ParentFolder
from hittade_client import (
    AsyncHittadeClient,
    BasicAuth,
    HostConfigurationSchema,
    HostDetailsSchema,
    PackageSchema,
    ServerContainerSchema,
    HittadeAPIError,
)

__author__ = "lundberg"

logger = logging.getLogger(__name__)


@dataclass
class Domain:
    id: str
    name: str | None = field(default=None)

    @classmethod
    def from_obj(cls, obj: FolderRead | ParentFolder | str) -> Self:
        match obj:
            case FolderRead() | ParentFolder():
                return cls(id=obj.id, name=obj.name)
            case str():
                return cls(id=obj)
            case _:
                raise NotImplementedError(f"Unknown domain type {type(obj)}")


@dataclass
class Asset:
    id: str
    name: str | None = field(default=None)
    domain: Domain | None = field(default=None)
    parent_assets: list[Self] = field(default_factory=list)
    children_assets: list[Self] = field(default_factory=list)

    @classmethod
    def from_obj(cls, obj: AssetRead | AssetWriteResponse | Dependency | str) -> Self:
        match obj:
            case AssetRead():
                return cls(
                    id=obj.id,
                    name=obj.name,
                    domain=Domain.from_obj(obj.folder),
                    parent_assets=(
                        [Asset.from_obj(parent) for parent in obj.parent_assets]
                    ),
                    children_assets=(
                        [Asset.from_obj(child) for child in obj.children_assets]
                    ),
                )
            case AssetWriteResponse():
                return cls(
                    id=obj.id,
                    name=obj.name,
                    domain=Domain.from_obj(obj.folder),
                    parent_assets=(
                        [Asset.from_obj(parent) for parent in obj.parent_assets]
                    ),
                )
            case Dependency():
                return cls(
                    id=obj.id,
                    name=obj.name,
                )
            case str():
                return cls(id=obj)
            case _:
                raise NotImplementedError(f"Unknown asset type {type(obj)}")


@dataclass
class Service:
    name: str
    dependencies: list[Self] = field(default_factory=list)


@dataclass
class Host:
    id: str
    name: str
    updated: datetime | None = None
    config: dict[str, dict[str, Any]] = field(default_factory=dict)
    details: HostDetailsSchema | None = None
    packages: list[PackageSchema] = field(default_factory=list)
    containers: list[ServerContainerSchema] = field(default_factory=list)
    _config: list[HostConfigurationSchema] = field(default_factory=list)
    _service: Service | None = None

    def _parse_config(self) -> dict[str, dict[str, Any]]:
        new_config: dict[str, dict[str, Any]] = {}
        for item in self._config:
            if item.ctype not in new_config:
                new_config[item.ctype] = {item.name: item.value}
                continue

            ctype_config = new_config[item.ctype]
            if item.name in ctype_config:
                current_value = ctype_config[item.name]
                if isinstance(current_value, list):
                    current_value.append(item.value)
                else:
                    # convert previous value to a list of that value and append the new value
                    ctype_config[item.name] = [current_value, item.value]
            else:
                ctype_config[item.name] = item.value
        return new_config

    @property
    def service(self) -> Service | None:
        if not self._service and self.config:
            if (
                "hiera_meta" in self.config
                and "meta_service_name" in self.config["hiera_meta"]
            ):
                self._service = Service(
                    name=self.config["hiera_meta"]["meta_service_name"]
                )
        return self._service

    async def update_config(
        self, client: AsyncHittadeClient, force: bool = False
    ) -> None:
        if not self.config or force:
            try:
                self._config = await client.get_host_config(host_id=self.id)
            except HittadeAPIError as e:
                logger.error(f"Failed to update config for host {self.id}: {e}")
                return None
            self.config = self._parse_config()
        return None

    async def update_host(
        self, client: AsyncHittadeClient, force: bool = False
    ) -> None:
        if not self.details or force:
            try:
                res = await client.get_host_details(host_id=self.id)
            except HittadeAPIError as e:
                logger.error(f"Failed to update details for host {self.id}: {e}")
                return None
            self.name = res.host.hostname
            self.details = res.details
            self.packages = res.packages
            self.containers = res.containers
            self._config = res.configs
            self._parse_config()
            self.updated = res.details.time
        return None


def get_ciso_client() -> AsyncCISOAssistantClient:
    ciso_pat = ApiToken(token=os.environ.get("CISO_API_TOKEN"))
    ciso_url = os.environ.get("CISO_URL")
    if ciso_pat is None:
        raise RuntimeError("Missing required environment variable: CISO_API_TOKEN")
    if ciso_url is None:
        raise RuntimeError("Missing required environment variable: CISO_URL")
    return CisoClient(base_url=ciso_url, auth=ciso_pat, verify=False)


def get_hittade_client(verify_tls: bool = True) -> AsyncHittadeClient:
    hittade_user = os.environ.get("HITTADE_USER")
    hittade_pass = os.environ.get("HITTADE_PASSWORD")
    hittade_url = os.environ.get("HITTADE_URL")
    if hittade_user is None:
        raise RuntimeError("Missing required environment variable: HITTADE_USER")
    if hittade_pass is None:
        raise RuntimeError("Missing required environment variable: HITTADE_PASSWORD")
    if hittade_url is None:
        raise RuntimeError("Missing required environment variable: HITTADE_URL")
    return AsyncHittadeClient(
        base_url=hittade_url,
        auth=BasicAuth(username=hittade_user, password=hittade_pass),
        verify=verify_tls,
    )


async def get_hittade_hosts(client: AsyncHittadeClient) -> dict[str, Host]:
    # Fetch hosts from Hittade
    hosts: dict[str, Host] = {}
    async with client:
        page = await client.list_hosts(limit=100)
        while page is not None:
            # load one page of hosts from hittade
            page_items = {
                item.hostname: Host(id=item.id, name=item.hostname)
                for item in page.items
            }
            # update config for each host from hittade
            config_updates = [
                page_items[hostname].update_config(client, force=True)
                for hostname in page_items
            ]
            for ex in await asyncio.gather(*config_updates, return_exceptions=True):
                if ex is not None:
                    # log any error when retrieving config
                    logger.error(f"Failed to update config for host: {ex}")
            # add host + host config to our cache
            hosts.update(page_items)
            # load next page
            page = await client.next_page(page)
    return hosts


def compile_hittade_services(hosts: dict[str, Host]) -> dict[str, list[str]]:
    services: dict[str, list[str]] = {}
    for hostname, host in hosts.items():
        if host.service:
            if services.get(host.service.name):
                services[host.service.name].append(hostname)
            else:
                services[host.service.name] = [hostname]
    logger.info(
        f"Found the following service tags for hosts in Hittade: {list(services.keys())}"
    )
    return services


async def get_current_domains(client: AsyncCISOAssistantClient) -> dict[str, Domain]:
    domains: list[FolderRead] = []
    async with client:
        folders = await client.list_folders(limit=100)
        while folders is not None:
            domains.extend(folders.results)
            folders = await client.next_page(paged_result=folders)

    domain_map = {d.name: Domain.from_obj(d) for d in domains}
    logger.info(
        f"Current domains configured in CISO Assistant: {list(domain_map.keys())}"
    )
    return domain_map


async def get_current_assets(
    client: AsyncCISOAssistantClient,
) -> dict[tuple[str, str], Asset]:
    assets: list[AssetRead | AssetWriteResponse] = []
    async with client:
        asset_page = await client.list_assets(limit=100)
        while asset_page is not None:
            assets.extend(asset_page.results)
            asset_page = await client.next_page(paged_result=asset_page)
    logger.debug(f"Assets in CISO Assistant: {assets=}")
    return {(a.folder.id, a.name): Asset.from_obj(a) for a in assets}


async def sync_hosts(
    client: AsyncCISOAssistantClient,
    services: dict[str, list[str]],
    domains: dict[str, Domain],
    assets: dict[tuple[str, str], Asset],
):
    for service_name, hostnames in services.items():
        if service_name not in domains:
            continue

        domain = domains[service_name]

        # Ensure service asset exists
        service_asset = assets.get((domain.id, service_name))
        if not service_asset:
            logger.info(f"Creating service asset: {service_name}")
            async with client:
                new_service_asset = await client.create_asset(
                    AssetWrite(
                        folder=domain.id,
                        name=service_name,
                        type=AssetType.PRIMARY_WRITE.value,
                    )
                )
            service_asset = Asset.from_obj(new_service_asset)
            assets[(domain.id, service_name)] = service_asset

        # Ensure host assets exist
        for hostname in hostnames:
            host_asset = assets.get((domain.id, hostname))
            if not host_asset:
                logger.info(f"Creating host asset: {hostname}")
                async with client:
                    await client.create_asset(
                        AssetWrite(
                            folder=domain.id,
                            name=hostname,
                            type=AssetType.SUPPORT_WRITE.value,
                            parent_assets=[service_asset.id],
                        )
                    )

        # Map parent_id -> list of child assets
        parent_to_children: dict[str, list[Asset]] = {}
        for asset in assets.values():
            if asset.parent_assets:
                for parent in asset.parent_assets:
                    if parent.id not in parent_to_children:
                        parent_to_children[parent.id] = []
                    parent_to_children[parent.id].append(asset)

        # Remove extraneous host assets
        if service_asset.id in parent_to_children:
            for child in parent_to_children[service_asset.id]:
                if child.name not in hostnames:
                    logger.info(f"Deleting extraneous asset: {child.name}")
                    async with client:
                        await client.delete_asset(asset_id=child.id)


async def main():
    hittade_client = get_hittade_client(verify_tls=False)
    ciso_client = get_ciso_client()

    hosts = await get_hittade_hosts(client=hittade_client)
    logger.info(f"Retrieved {len(hosts)=} hosts from Hittade")
    services = compile_hittade_services(hosts)

    # get current domains
    domains = await get_current_domains(client=ciso_client)
    # get current assets
    assets = await get_current_assets(client=ciso_client)

    # Sync hosts Hittade -> CISO Assistant
    await sync_hosts(
        client=ciso_client, services=services, domains=domains, assets=assets
    )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
    logger.info("Hosts have been synced to Cisco Assistant.")
