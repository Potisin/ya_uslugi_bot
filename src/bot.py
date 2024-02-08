import asyncio
import logging
import traceback

from aiogram import Bot, Dispatcher, types
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from sqlalchemy import select, update

from config import TG_BOT_TOKEN, CHAT_ID
from database import async_session
from models import Order
from utils import get_keywords, set_keywords

bot = Bot(TG_BOT_TOKEN, parse_mode="HTML")
dp = Dispatcher()
chat_id = CHAT_ID

logger = logging.getLogger(__name__)


class KeywordsState(StatesGroup):
    keywords = State()


async def on_startup():
    logger.info('Bot started')
    print('bot started')


async def on_shutdown():
    logger.info('Bot stopped')
    print('bot stopped')


@dp.message(CommandStart())
async def start(message: types.Message):
    await message.answer(f'Привет! Вот твой чат айди: {message.chat.id}. Ты можешь изменить ключевые слова, '
                         f'отправив команду /edit_keywords')


@dp.message(Command('edit_keywords'))
async def edit_keywords(message: types, state: FSMContext):
    keywords = get_keywords()
    await message.answer(f'Ниже уже существующий список ключевых слов. '
                         f'Просто отправь мне отредактированный список, если хочешь что-то изменить. '
                         f'Не забывай разделять слова запятыми.')
    await message.answer(','.join(keywords))
    await state.set_state(KeywordsState.keywords)


@dp.message(KeywordsState.keywords)
async def edit_process(message: types, state: FSMContext):
    keywords = [keyword.strip().lower() for keyword in message.text.split(',')]
    try:
        set_keywords(keywords)
    except Exception:
        await message.answer('Что-то пошло не так. Проверь список, '
                             'убедись что разделил слова запятыми и отправь еще раз')
        await state.set_state(KeywordsState.keywords)
        return
    await message.answer('Отлично! Список ключевых слов изменен.')
    await state.clear()


async def check_db_and_inform():
    async with async_session() as session:
        while True:
            try:
            # получает заказы из базы, которые еще не были отправлены
                stmt = select(Order).filter_by(is_invited=True, is_tg_sent=False)
                result = await session.scalars(stmt)
                orders = result.all()
                for order in orders:
                    # пробегается по заказам, отправляет в тг, изменяет флаг Отправлено в тг
                    await bot.send_message(chat_id,
                                           f'Новый заказ. \n'
                                           f'Нужно сделать: {order.title} \n'
                                           f'Ссылка: {order.url}')
                    stmt = update(Order).filter_by(id=order.id).values(is_tg_sent=True)
                    await session.execute(stmt)
                    await session.commit()
            except Exception as ex:
                print(ex)
                print(traceback.format_exc())
                logger.error(traceback.format_exc())
                logger.error(ex)
                await bot.send_message(chat_id, f'Ошибка: {ex}. Подробнее в лог файле')
            await asyncio.sleep(10)


async def main() -> None:
    await bot.delete_webhook(drop_pending_updates=True)
    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)
    asyncio.create_task(check_db_and_inform()) # создаем фоновую задачу
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
