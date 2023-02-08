"""Управление настройками ботов, массовой рассылкой и чатом.

Не чаще 1 сообщения в секунду пользователю, не чаще 30 сообщений в секунду
разным пользователям:
https://core.telegram.org/bots/faq#broadcasting-to-users
"""

from datetime import datetime, timezone
from typing import Final, Callable, Literal
import logging
import json
import collections
from threading import Thread

from telebot import TeleBot
from telebot.types import CallbackQuery, User, InputMediaPhoto
from telebot.apihelper import ApiTelegramException
from telebot.custom_filters import TextMatchFilter
from telebot.handler_backends import RedisHandlerBackend
from gql import gql

from metrix import metrix, bot as mxbot, user as mxusr
from metrix.schema import (
    BotsSettings as BotsSettingsOp,
    Notifications,
    AdminMsgs,
    ConfigScr,
    ConfigKeyEnum_enum as MxCfgKey
)
from _types import JsonDict
import storage
from handlers import (
    address as addrhdlr,
    card as cardhdlr,
    cart as carthdlr,
    order as orderhdlr,
    payment as pmnthdlr,
    start as starthdlr,
    chat as chathdlr
)
from usrctx import UsrCtx
from subscr import Subscription
import tools
import message as mestools
import config as cfg

BotSettings = tuple[
    TeleBot, str, bool, bool, bool, bool, int, str, bool, bool, bool
]

_LOGGER: Final = logging.getLogger('sstgb')
_MX_CFG_SCR_DN: Final = gql(ConfigScr.Meta.document)


def _get_query_pref_filter(prefix: str) -> Callable[[CallbackQuery], bool]:
    return lambda query: query.data.startswith('!' + prefix)


def _create_tg_api(tg_token: str) -> TeleBot:
    # https://www.pythonanywhere.com/forums/topic/12368/
    # Потоки создает сервер приложений, нет необходимости в пуле потоков
    # для обработчиков

    # NOTE register_next_step_handler не будет работать корректно в
    # случае с использованием нескольких процессов: регистрировать может
    # объект в одном процессе, а принимать следующее сообщение объект в
    # другом. Нужно заменить MemoryHandlerBackend, чтобы это исправить:
    # https://github.com/eternnoir/pyTelegramBotAPI/blob/d1d5b9effb7d51c2dd706ebbaa70692042f0befd/telebot/__init__.py#L67

    tg_api = TeleBot(
        tg_token,
        threaded=False,
        next_step_backend=RedisHandlerBackend(host=cfg.CACHE_HOST)
    )

    tg_api.add_custom_filter(TextMatchFilter())

    commands = ('Добавить адрес', 'Изменить адрес', 'Мои карты', '/start')

    tg_api.message_handler(
        content_types=['document', 'photo', 'video', 'text'],
        func=lambda message: message.text not in commands
    )(chathdlr.send_client_mes)

    tg_api.message_handler(commands=['start'])(starthdlr.greet)
    tg_api.callback_query_handler(
            _get_query_pref_filter('is'))(starthdlr.init_state)

    tg_api.message_handler(text=commands[0])(addrhdlr.add_addr)
    tg_api.message_handler(text=commands[1])(addrhdlr.send_other_addrs)
    tg_api.callback_query_handler(
            _get_query_pref_filter('ca'))(addrhdlr.change_addr)

    tg_api.message_handler(text=commands[2])(cardhdlr.send_cards)
    tg_api.callback_query_handler(
            _get_query_pref_filter('dc'))(cardhdlr.delete_card)

    tg_api.callback_query_handler(
            _get_query_pref_filter('sc'))(carthdlr.sell_cart)

    tg_api.callback_query_handler(
            _get_query_pref_filter('co'))(orderhdlr.cancel_order)
    tg_api.callback_query_handler(
            _get_query_pref_filter('eo'))(orderhdlr.estimate_order)

    tg_api.callback_query_handler(
            _get_query_pref_filter('po'))(pmnthdlr.pay_order)
    tg_api.callback_query_handler(
            _get_query_pref_filter('cp'))(pmnthdlr.change_pmnt_type)

    return tg_api


def _get_bot_photo(me: User,
                   org_id: str,
                   tg_api: TeleBot) -> str | None:
    if not (photos := tg_api.get_user_profile_photos(me.id, limit=1).photos):
        return None

    # TODO Лучше перезапиывать старую картинку и сохранять File id, а не путь

    mx_file = tools.save_tg_file(
            tg_api, org_id, photos[0][1].file_id, 'image/jpeg')

    if not mx_file:
        return None

    return mx_file['path']


def _check_tg_api(tg_token: str, org_id: str) -> TeleBot | None:
    import father

    if tg_token in BOTS_SETTINGS:  # только обновить настройки
        tg_api = BOTS_SETTINGS[tg_token][0]
    else:  # новый бот
        tg_api = _create_tg_api(tg_token)

        try:
            me = tg_api.get_me()
        except ApiTelegramException:  # например, невалидный токен
            _LOGGER.exception(
                'Не удалось получить данные бота '
                + tools.disguise_token(tg_api.token)
            )
            return None

        if storage.take_control():
            usr_ctx = UsrCtx(tg_api=tg_api, org_id=org_id)

            father.init(usr_ctx)

            photo = _get_bot_photo(me, org_id, tg_api)
            mxbot.set_bot_data(me.username, me.first_name, photo, usr_ctx)

    return tg_api


def _fill_settings(tg_api: TeleBot, row: dict) -> None:
    org_settings = row['org']['settings'] or {
        'hasOnlinePmnt': False,
        'hasCardPmnt': False,
        'hasCashPmnt': False
    }

    bot_settings: BotSettings = (
        tg_api,
        row['orgId'],
        row['hasNps'],
        row['needPersonsNum'],
        row['authOnStart'],
        row['isUsable'],
        row['maxOrderCount'],
        row['org']['currencyUnit'] or '₽',
        org_settings['hasOnlinePmnt'],
        org_settings['hasCardPmnt'],
        org_settings['hasCashPmnt']
    )

    BOTS_SETTINGS[tg_api.token] = bot_settings
    # Иногда удобней искать по организации
    ORGS_BOT_SETTINGS[row['orgId']] = bot_settings


def _apply_bots_settings(update: JsonDict) -> bool:
    MX_NOTIFS_LOCK.acquire()
    ADMIN_MSGS_LOCK.acquire()

    if cfg.MX_SETTINGS:
        rows = update['TelegramSettingsReference']
    else:
        with open('settings.json', 'r') as file:
            rows = json.load(file)

    tokens: set[str] = set()  # актуальные боты

    for row in rows:  # регистрируем бота
        if not (tg_api := _check_tg_api(row['tgToken'], row['orgId'])):
            continue

        _fill_settings(tg_api, row)

        tokens.add(tg_api.token)

    # Удалить старых ботов
    # excess
    for ex_token in set(BOTS_SETTINGS.keys()) - tokens:
        org_id = BOTS_SETTINGS[ex_token][1]

        del BOTS_SETTINGS[ex_token]
        del ORGS_BOT_SETTINGS[org_id]

    MX_NOTIFS_LOCK.notify()
    MX_NOTIFS_LOCK.release()
    ADMIN_MSGS_LOCK.notify()
    ADMIN_MSGS_LOCK.release()

    return True


def _send_org_notif(notif: dict, usr_ids: set[str], usr_ctx: UsrCtx) -> int:
    images = [
        InputMediaPhoto(
            f'https://{cfg.VITE_MX_STO_PATH}/{image["path"]}',
            notif['text'] if i == 0 else None
        ) for i, image in enumerate(notif['images'])
    ]

    recip_count = 0

    for usr_id in usr_ids:
        usr_ctx.__dict__['usr_id'] = usr_id

        try:
            if images:  # уведомление с картинками
                usr_ctx.tg_api.send_media_group(usr_id, images)
            else:
                mestools.send_mes(notif['text'], usr_ctx=usr_ctx)
        except ApiTelegramException as err:
            if err.error_code == 403:  # бот остановлен
                mxusr.update_bot_status(True, usr_ctx)
            else:
                _LOGGER.exception(
                    f'Не удалось отправить уведомление пользователю {usr_id}'
                )
        else:
            recip_count += 1

    return recip_count


def _proc_mx_notifs(update: JsonDict) -> bool:
    # NOTE Несколько сервисов не должны обслуживать одну организацию
    if not storage.take_control():
        return True

    # Подготовить данные
    notifs_map = collections.defaultdict(list)

    for item in update['MailingInfoRg']:
        notifs_map[item['orgId']].append(item)

    # Отправить уведомления

    MX_NOTIFS_LOCK.wait_for(lambda: bool(BOTS_SETTINGS))

    for org_id, notifs in notifs_map.items():
        _LOGGER.info(
            (f'Начало рассылки уведомлений ({len(notifs)}) для организации '
             f'{org_id}')
        )

        notif_ids = []
        usr_ctx = UsrCtx(org_id=org_id)

        # NOTE Брать ИД не из локальной базы, а из Хасуры. После
        # обновления бота состояние может быть очищено.

        # Брать также из User, чтобы зацепить активных пользователей до
        # появления BotUser

        responses = [
            mxusr.get_bot_users(usr_ctx=usr_ctx),
            mxusr.get_usrs_tg(usr_ctx=usr_ctx)
        ]

        if any([response is None for response in responses]):
            return False

        usr_ids = {
            item['tgUsrId'] for response in responses
            for item in response  # type: ignore[union-attr]
        }

        if bot_settings := ORGS_BOT_SETTINGS.get(org_id):
            usr_ctx.__dict__['tg_api'] = bot_settings[0]
        else:
            _LOGGER.warning(
                f'Рассылка пропущена: организация {org_id} не обслуживается'
            )
            continue

        recip_count = 0

        for notif in notifs:
            notif_ids.append(notif['id'])

            if bot_settings:
                recip_count = _send_org_notif(notif, usr_ids, usr_ctx)

        # NOTE Намеренно берем количество получателей последнего
        # уведомления в пакете
        mxbot.deliver_notifs(notif_ids, recip_count, usr_ctx)

    return False


def _update_mx_cfg(update: JsonDict) -> Literal[True]:
    from geocoding import geocoding

    mx_cfg = {row['id']: row for row in update['Config']}

    geocoding.update_def_srv(mx_cfg)

    return True


def _proc_admin_msgs(update: JsonDict) -> Literal[False]:
    _ADMIN_MSGS_ARGS['from'] = datetime.now(timezone.utc).isoformat()

    ADMIN_MSGS_LOCK.wait_for(lambda: bool(BOTS_SETTINGS))

    for message in update['BotMessage']:
        if not (bot_settings := ORGS_BOT_SETTINGS.get(message['orgId'])):
            _LOGGER.warning(
                ('Отправлено сообщение из необслуживаемой организации: '
                 f'{message["orgId"]}')
            )
            continue

        if not message['authorId']:  # отправленные пользователем
            continue

        chathdlr.send_admin_mes(
            message['text'],
            message['files'],
            UsrCtx(
                org_id=message['orgId'],
                usr_id=message['tgUsrId'],
                tg_api=bot_settings[0]
            )
        )

    return False


BOTS_SETTINGS: Final[dict[str, BotSettings]] = {}
ORGS_BOT_SETTINGS: Final[dict[str, BotSettings]] = {}

_BOTS_SETTINGS_SCR: Final = Subscription(
        BotsSettingsOp.Meta.document, _apply_bots_settings, 3)
BOTS_SETTINGS_LOCK: Final = _BOTS_SETTINGS_SCR.lock

_MX_NOTIFS_SCR: Final = Subscription(
        Notifications.Meta.document, _proc_mx_notifs, 10)
MX_NOTIFS_LOCK: Final = _MX_NOTIFS_SCR.lock

_MX_CFG_SCR: Final = Thread(
    target=metrix.watch,
    args=(
        _MX_CFG_SCR_DN,
        _update_mx_cfg,
        {'params': [
            MxCfgKey.DADATA_API_KEY,
            MxCfgKey.DADATA_SECRET
        ]}
    )
)

_ADMIN_MSGS_ARGS: Final = {'from': datetime.now(timezone.utc).isoformat()}
_ADMIN_MSGS_SCR: Final = Subscription(
        AdminMsgs.Meta.document, _proc_admin_msgs, 3, _ADMIN_MSGS_ARGS)
ADMIN_MSGS_LOCK: Final = _ADMIN_MSGS_SCR.lock


def run():
    """Запустить подписки."""
    _BOTS_SETTINGS_SCR.start()
    _MX_NOTIFS_SCR.start()
    _MX_CFG_SCR.start()

    if cfg.ADMIN_MSGS_SCR:
        _ADMIN_MSGS_SCR.start()
