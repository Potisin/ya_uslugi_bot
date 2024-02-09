import asyncio
import json
import logging
import os
import time
import traceback

from selenium import webdriver
from selenium.common import NoSuchElementException

from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.webdriver import WebDriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.wait import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError

from database import async_session
from models import Order
from utils import get_keywords

logger = logging.getLogger(__name__)


def get_chrome_driver() -> WebDriver:
    options = Options()
    options.add_argument('--disable-blink-features=AutomationControlled')
    options.add_argument("--disable-notifications")
    options.add_argument("--disable-infobars")
    options.add_argument("--disable-save-password-bubble")
    options.add_argument("--enable-automation")
    options.add_argument('--headless=new')
    options.add_experimental_option("excludeSwitches", ['enable-automation'])
    driver = webdriver.Chrome(options=options)
    return driver


class YaUslugiScraper:
    def __init__(self):
        self.driver = get_chrome_driver()
        self.cookies_path = 'data/cookies.json'
        self.keywords = get_keywords()
        self.original_window = None

    async def run(self) -> None:
        """Главная функция-цикл управления скриптом"""
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self.connect_to_site)
        while True:
            try:
                await self.browsing_orders()
                await self.check_invites()
                time.sleep(60)

            except Exception as ex:
                print(ex)
                print(traceback.format_exc())
                logger.error(traceback.format_exc())
                logger.error(ex)
                await loop.run_in_executor(None, self.stop)

    def connect_to_site(self) -> None:
        """Заходит най сайт, добавляет куки, переходит на страницу с заказами, устанавливает фильтр"""
        driver = self.driver
        driver.maximize_window()
        self.original_window = driver.current_window_handle
        driver.get(f'https://uslugi.yandex.ru/')
        self.add_cookie_to_driver()
        driver.refresh()
        time.sleep(1)
        driver.get(f'https://uslugi.yandex.ru/cab')
        time.sleep(3)
        # клик по кнопке "Поиск заказов" т.к. в ней заложены параметры с категориями
        driver.find_element(By.XPATH, "//a[text()='Поиск заказов']").click()
        time.sleep(3)
        # установка фильтра "Показывать любые" независимо от количества откликов
        reaction_count_filter = driver.find_element(By.XPATH,
                                                    "//span[contains(text(), 'Показывайте мне заказы')]"
                                                    "/ancestor::div[contains(@class, 'Row')]/descendant::button")
        reaction_count_filter.click()
        time.sleep(1)
        WebDriverWait(driver, 10).until(EC.element_to_be_clickable(
            (By.XPATH, "//div[contains(@class, 'menu__item') and .//span[text()='Любые']]"))).click()
        time.sleep(3)

    async def browsing_orders(self) -> None:
        """Обходит все страницы с заказами, добавляет в БД, откликается, как только встречает заказ,
         который уже есть в БД, прекращает выполнение, выходит в главный цикл"""
        driver = self.driver
        while True:  # проход по страницам
            order_cards = (WebDriverWait(driver, 10).until(
                EC.visibility_of_all_elements_located((By.CSS_SELECTOR, '.OrderCard2.Card'))))
            # обходит все заказы на странице
            for order in order_cards:
                title = order.find_element(By.CSS_SELECTOR, '.OrderCard2-TitleRow').text.lower()
                # проверка на совпадение по ключевым словам
                for keyword in self.keywords:
                    if keyword.lower() in title:
                        # получение данных и добавление в БД
                        url = order.find_element(By.CSS_SELECTOR, '.OrderCard2-TitleLink').get_attribute('href')
                        description = order.find_element(By.CSS_SELECTOR, '.OrderCard2-Description').text.lower()
                        contact = order.find_element(By.CSS_SELECTOR, '.OrderCard2-CustomerBadge').text.lower()
                        async with async_session() as session:
                            try:
                                order = Order(title=title, url=url, description=description,
                                              contact=contact)
                                session.add(order)
                                await session.commit()
                                self.apply_for_order(url)  # откликается только если в бд все сохранилось успешно
                            # если заказ уже есть в базе, то выходим, т.к. сортировка по дате,
                            # а значит все остальные заказы уже есть в базе
                            except IntegrityError:
                                await session.rollback()
                                return

            # управление пагинацией
            try:
                driver.find_element(By.XPATH, '//a[@rel="next"]').click()
            except NoSuchElementException:
                # возвращение к первой странице
                driver.find_element(By.XPATH, "//a[text()='Поиск заказов']").click()
                return
            time.sleep(3)

    def apply_for_order(self, url: str) -> None:
        """Устанавливает тип цены, цену, текст, откликается на заказ"""
        driver = self.driver
        self.new_window('open')
        driver.get(url)
        time.sleep(3)
        # устанавливает тип цены "за услугу"
        try:
            driver.find_element(By.CLASS_NAME, 'select2__button').click()
            time.sleep(1)
            WebDriverWait(driver, 10).until(EC.element_to_be_clickable(
                (By.XPATH, "//div[contains(@class, 'menu__item') and .//span[text()='за услугу']]"))).click()
            respond_message_input = driver.find_element(By.CLASS_NAME, 'Textarea-Control')
            respond_message_input.send_keys('') # ЗДЕСЬ можно указать сообщение, которое будет отправлено при отклике
            # устанавливает стоимость
            price_input = driver.find_element(By.CLASS_NAME, 'textinput__control')
            price_input.send_keys(1000)
            time.sleep(1)
            driver.find_element(By.CLASS_NAME, 'Button2_type_submit')
            time.sleep(3)

        except NoSuchElementException as ex:
            # в ходе тестирования или при других обстоятельствах может возникнуть ситуация, что в БД записи нет,
            # а фактически отклик уже оставлен. в этом случае перехватываем ошибку NoSuchElementException
            print(f'Ошибка при добавление отклика: {ex}. Вероятно на этот заказ уже оставлен отклик')
            logger.error(f'Ошибка при добавление отклика: {ex}. Вероятно на этот заказ уже оставлен отклик')

        self.new_window('close')

    async def check_invites(self) -> None:
        """Проверяет наличие сообщений в чате по заказам и приглашения, вносит изменения в БД"""
        driver = self.driver
        self.new_window('open')
        driver.get('https://uslugi.yandex.ru/cab/connections')
        time.sleep(3)

        await self.update_orders('CustomerConnectionsListItem', '.CustomerConnectionsListItem-MoreLink')
        await self.update_orders('OrderCard2', '.OrderCard2-MoreLink')
        self.new_window('close')

    async def update_orders(self, card_class: str, link_selector: str):
        """Изменяет параметр is_invited у заказов, на которые пригласили или добавили в чат"""
        order_cards = self.driver.find_elements(By.CLASS_NAME, card_class)
        for order in order_cards:
            url = order.find_element(By.CSS_SELECTOR, link_selector).get_attribute('href')
            async with async_session() as session:
                stmt = update(Order).filter_by(url=url).values(is_invited=True)
                await session.execute(stmt)
                await session.commit()

    def new_window(self, action: str) -> None:
        """Управляет новым окном(вкладкой)"""
        driver = self.driver
        if action == "open":
            # Открытие новой вкладки
            driver.execute_script("window.open('');")
            new_window = [window for window in driver.window_handles if window != self.original_window][0]
            driver.switch_to.window(new_window)
        elif action == "close":
            driver.close()
            driver.switch_to.window(self.original_window)

    def stop(self) -> None:
        self.driver.close()
        self.driver.quit()
        print("Работа в браузере остановлена")

    def add_cookie_to_driver(self) -> None:
        """Преобразовывает сохраненные куки из браузера в куки, которые поддерживаются селениумом """
        if os.path.exists(self.cookies_path):
            time.sleep(2)

            # Загрузка и добавление куки
            with open(self.cookies_path, 'r') as file:
                cookies = json.load(file)
                for cookie in cookies:
                    # Удаление неподдерживаемых полей
                    cookie.pop('id', None)
                    cookie.pop('hostOnly', None)
                    cookie.pop('session', None)
                    cookie.pop('storeId', None)
                    cookie.pop('httpOnly', None)

                    # Преобразование поля expirationDate в expiry
                    if 'expirationDate' in cookie:
                        cookie['expiry'] = int(cookie.pop('expirationDate'))

                    # Корректировка значения sameSite
                    if 'sameSite' in cookie:
                        cookie['sameSite'] = 'None'

                        # Добавление куки
                    try:
                        self.driver.add_cookie(cookie)
                    except Exception as e:
                        print(f"Ошибка при добавлении куки: {e}")

        else:
            print("Куки не найдены. Обратитесь к readme для получения информации о создании cookies.json")


if __name__ == "__main__":
    scraper = YaUslugiScraper()
    asyncio.run(scraper.run())
