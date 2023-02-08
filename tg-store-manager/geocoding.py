"""Базовый модуль геокодирования."""

import logging
from types import ModuleType
from typing import Callable, Any, Final, ParamSpec, Concatenate, Union
from threading import Thread

from flask import g
from dadata import Dadata
from geopy.geocoders import Nominatim, Yandex
from gql import gql

from . import dadata as dd, osm, yandex
from _types import Coords, HaddrParts, AddrSugg, JsonDict
from metrix import metrix
from metrix.schema import GeocSettingsScr, ConfigKeyEnum_enum as MxCfgKey

GeocService = Union[Dadata, Yandex, Nominatim]
SrvParams = Union[tuple[GeocService, dict], None]
FuncParams = ParamSpec('FuncParams')

_LOGGER: Final = logging.getLogger('sstgb')

_GEOC_SERVICES: Final[dict[str, SrvParams]] = {}
_def_service: SrvParams = None

# Geocoding settings subscription document node
_GEOC_SETTINGS_SCR_DN: Final = gql(GeocSettingsScr.Meta.document)

_GEOC_MODULES: Final = {Dadata: dd, Yandex: yandex, Nominatim: osm}


def update_def_srv(config: dict) -> None:
    """Обновить сервис геокодирования по умолчанию для всех организаций."""
    global _def_service

    _def_service = _get_service(
        'DADATA',
        config[MxCfgKey.DADATA_API_KEY.value]['value'],
        config[MxCfgKey.DADATA_SECRET.value]['value'],
        _def_service
    )


def _get_service(srv_name: str,
                 first_key: str | None,
                 second_key: str | None,
                 old_params: SrvParams) -> SrvParams:
    """Получить сервис геокодирования.

    Если это возможно, вернет объект старого сервиса вместо создания нового,
    чтобы сохранить контекст
    """
    def print_warn() -> None:
        _LOGGER.warning(
                'Недостаточно данных для инициализации сервиса геокодирования')

    match srv_name:
        case 'DADATA':
            if not first_key or not second_key:
                print_warn()
                return None

            # Использует в реализации httpx Client, который использует
            # пул соединений
            # Потокобезопасный (можно вызывать в разных потоках)
            ctor = Dadata
            args = {'token': first_key, 'secret': second_key}
        case 'OSM':
            ctor = Nominatim
            args = {'user_agent': 'sstg-bot'}
        case 'YANDEX':
            if not first_key:
                print_warn()
                return None

            ctor = Yandex
            args = {'api_key': first_key}
        case _:
            return None

    if not old_params or old_params[0].__class__ != ctor \
            or old_params[1] != args:
        return ctor(**args), args

    return old_params


def _apply_geoc_settings(update: JsonDict) -> bool:
    org_ids: set[str] = set()

    for row in update['Organization']:
        org_ids.add(row['orgId'])

        _GEOC_SERVICES[row['orgId']] = _get_service(
            row['settings']['service'],
            row['settings']['firstKey'],
            row['settings']['secondKey'],
            _GEOC_SERVICES.get(row['orgId'])
        )

    for org_id in set(_GEOC_SERVICES.keys()) - org_ids:
        del _GEOC_SERVICES[org_id]

    return True


def _service(
    func: Callable[Concatenate[ModuleType, GeocService, FuncParams], Any]
) -> Callable[FuncParams, Any]:
    def wrapper(*args: FuncParams.args, **kwargs: FuncParams.kwargs) -> Any:
        if g.org_id not in _GEOC_SERVICES:
            srv_params = _def_service
        else:
            srv_params = _GEOC_SERVICES[g.org_id]

        if not srv_params:
            return None

        service = srv_params[0]
        return func(_GEOC_MODULES[service.__class__], service, *args, **kwargs)

    return wrapper


@_service
def get_addr_coords(module: ModuleType,
                    service: GeocService,
                    addr: str) -> Coords | None:
    """Получить координаты по строке с адресом."""
    return module.get_addr_coords(service, addr)


@_service
def parse_coords_addr(module: ModuleType,
                      service: GeocService,
                      lat: float,
                      lon: float) -> HaddrParts | None:
    """Получить части адреса по координатам."""
    return module.parse_coords_addr(service, lat, lon)


@_service
def parse_addr(module: ModuleType,
               service: GeocService,
               addr: str) -> HaddrParts | None:
    """Получить части адреса по строке с адресом."""
    return module.parse_addr(service, addr)


@_service
def get_addr_suggs(module: ModuleType,
                   service: GeocService,
                   addr: str,
                   count: int) -> list[AddrSugg]:
    """Получить варианты адресов по строке с адресом."""
    res: list[AddrSugg] = []

    for value, parts, coords in module.get_addr_suggs(service, addr):
        if len(res) == count:
            break

        # Если части не все, то можно без координат
        if not parts or len(list(filter(None, parts))) == 3 and not coords:
            continue

        res.append((value, parts, coords))

    return res


_GEOC_SETTINGS_SCR: Final = Thread(
    target=metrix.watch,
    args=(_GEOC_SETTINGS_SCR_DN, _apply_geoc_settings)
)


def run():
    """Запустить подписки."""
    _GEOC_SETTINGS_SCR.start()
