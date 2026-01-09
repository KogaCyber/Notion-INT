#!/usr/bin/env python3
"""
Notion Webhook Server - Полное извлечение ВСЕХ данных из Notion
Сервер для получения webhook уведомлений от Notion API
"""

import os
import asyncio
import logging
import hmac
import hashlib
import json
import re
from datetime import datetime
from typing import Dict, Any, List
from fastapi import FastAPI, Request, HTTPException, BackgroundTasks
from fastapi.responses import JSONResponse
import uvicorn
from dotenv import load_dotenv

from notion_integration import NotionIntegration
from telegram_client import TelegramIntegration
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters

# Загрузка переменных окружения
load_dotenv()

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('webhook_server.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

app = FastAPI(title="Notion-Telegram Webhook", version="1.0.0")

# Middleware для логирования всех запросов
@app.middleware("http")
async def log_requests(request: Request, call_next):
    """Логирование всех входящих запросов"""
    start_time = datetime.now()
    logger.info(f"Входящий запрос: {request.method} {request.url.path}?{request.url.query}")
    logger.info(f"Headers: {dict[str, str](request.headers)}")
    
    try:
        response = await call_next(request)
        process_time = (datetime.now() - start_time).total_seconds()
        logger.info(f"Ответ: {response.status_code} за {process_time:.3f}с")
        return response
    except Exception as e:
        logger.error(f"Ошибка при обработке запроса: {e}", exc_info=True)
        raise

# Инициализация клиентов
notion_client = None
telegram_client = None
telegram_app = None  # Для обработки сообщений из Telegram

class WebhookProcessor:
    def __init__(self):
        self.webhook_secret = os.getenv('NOTION_WEBHOOK_SECRET')
        self.logger = logging.getLogger(__name__)
    
    def verify_signature(self, body: bytes, signature: str) -> bool:
        """Проверка подписи webhook"""
        # Временно отключаем проверку подписи для отладки
        self.logger.info("Пропускаем проверку подписи для отладки")
        return True
    
    def get_database_name(self, database_id: str) -> str:
        """Получение названия базы данных"""
        try:
            database_data = notion_client.client.databases.retrieve(database_id=database_id)
            if database_data and 'title' in database_data and database_data['title']:
                return database_data['title'][0].get('plain_text', 'Unknown Database')
            return 'Unknown Database'
        except Exception as e:
            self.logger.error(f"Ошибка получения названия базы данных {database_id}: {e}")
            return 'Unknown Database'
    
    def get_hierarchy_components(self, page_id: str, database_id: str = None) -> Dict[str, str]:
        """Получение компонентов иерархии отдельно"""
        try:
            hierarchy = {
                'department': '',
                'project': '',
                'tasks': ''
            }
            
            if database_id:
                self.logger.info(f"Using database_id from webhook: {database_id}")
                database_name = self.get_database_name(database_id)
                hierarchy['tasks'] = database_name
                
                # Получаем иерархию базы данных
                try:
                    database_data = notion_client.client.databases.retrieve(database_id=database_id)
                    db_parent = database_data.get('parent', {})
                    self.logger.info(f"Database parent: {db_parent}")
                    
                    if db_parent.get('type') == 'page_id':
                        parent_page_id = db_parent.get('page_id')
                        self.logger.info(f"Getting database parent page: {parent_page_id}")
                        page_data = notion_client.get_page_data(parent_page_id)
                        if page_data:
                            # Получаем заголовок родительской страницы
                            title = "No Title"
                            if 'properties' in page_data:
                                for prop_name, prop_value in page_data['properties'].items():
                                    if prop_value.get('type') == 'title':
                                        title_array = prop_value.get('title', [])
                                        if title_array:
                                            title = title_array[0].get('plain_text', 'No Title')
                                            break
                            hierarchy['project'] = title
                            
                            # Проверяем родителя страницы
                            parent = page_data.get('parent', {})
                            if parent.get('type') == 'page_id':
                                parent_page_id = parent.get('page_id')
                                parent_page_data = notion_client.get_page_data(parent_page_id)
                                if parent_page_data:
                                    parent_title = "No Title"
                                    if 'properties' in parent_page_data:
                                        for prop_name, prop_value in parent_page_data['properties'].items():
                                            if prop_value.get('type') == 'title':
                                                title_array = prop_value.get('title', [])
                                                if title_array:
                                                    parent_title = title_array[0].get('plain_text', 'No Title')
                                                    break
                                    hierarchy['department'] = parent_title
                    elif db_parent.get('type') == 'block_id':
                        # База данных находится внутри блока
                        block_id = db_parent.get('block_id')
                        self.logger.info(f"Getting database parent block: {block_id}")
                        try:
                            block_data = notion_client.client.blocks.retrieve(block_id=block_id)
                            if block_data.get('type') == 'toggle':
                                toggle_text = block_data.get('toggle', {}).get('rich_text', [])
                                if toggle_text:
                                    block_title = toggle_text[0].get('plain_text', 'Unknown Block')
                                    self.logger.info(f"Block title: {block_title}")
                                    hierarchy['project'] = block_title
                            
                            # Получаем иерархию родительского блока
                            block_parent = block_data.get('parent', {})
                            self.logger.info(f"Block parent: {block_parent}")
                            if block_parent.get('type') == 'page_id':
                                parent_page_id = block_parent.get('page_id')
                                self.logger.info(f"Getting block parent page: {parent_page_id}")
                                parent_page_data = notion_client.get_page_data(parent_page_id)
                                if parent_page_data:
                                    parent_title = "No Title"
                                    if 'properties' in parent_page_data:
                                        for prop_name, prop_value in parent_page_data['properties'].items():
                                            if prop_value.get('type') == 'title':
                                                title_array = prop_value.get('title', [])
                                                if title_array:
                                                    parent_title = title_array[0].get('plain_text', 'No Title')
                                                    break
                                    hierarchy['department'] = parent_title
                        except Exception as e:
                            self.logger.error(f"Ошибка получения блока {block_id}: {e}")
                except Exception as e:
                    self.logger.error(f"Ошибка получения базы данных {database_id}: {e}")
            
            return hierarchy
            
        except Exception as e:
            self.logger.error(f"Ошибка получения компонентов иерархии для {page_id}: {e}")
            return {'department': '', 'project': '', 'tasks': ''}
    
    def extract_all_fields(self, page_data: Dict, database_id: str = None) -> Dict:
        """Извлечение ВСЕХ полей из страницы Notion"""
        try:
            properties = page_data.get('properties', {})
            
            # Получаем компоненты иерархии отдельно
            hierarchy_components = self.get_hierarchy_components(page_data.get('id', ''), database_id)
            
            # Извлекаем ВСЕ возможные поля
            extracted_data = {
                'id': page_data.get('id', ''),
                'title': self._extract_title(properties),
                'department': hierarchy_components.get('department', ''),
                'project': hierarchy_components.get('project', ''),
                'tasks': hierarchy_components.get('tasks', ''),
                'description': self._extract_rich_text(properties, 'Description'),
                'status': self._extract_status(properties, 'Status'),
                'deadline': self._extract_date(properties, 'Deadline'),
                'start_date': self._extract_date(properties, 'Start Date'),
                'executor': self._extract_people(properties, 'Executor'),
                'assigned_by': self._extract_people(properties, 'Assigned By'),
                'telegram_username': self._extract_multi_select(properties, 'Telegram Username'),
                'project_relation': self._extract_relation(properties, 'Projects (1)'),
                'parent_item': self._extract_relation(properties, 'Parent item'),
                'blocked_by': self._extract_relation(properties, 'Blocked by'),
                'blocking': self._extract_relation(properties, 'Blocking'),
                'sub_item': self._extract_relation(properties, 'Sub-item'),
                'strategy_file': self._extract_files(properties, 'Strategy file'),
                'strategy_link': self._extract_url(properties, 'Strategy Link'),
                'url': page_data.get('url', ''),
                'created_time': self._extract_created_time(page_data),
                'last_edited_time': self._extract_last_edited_time(page_data),
                'archived': page_data.get('archived', False),
                'in_trash': page_data.get('in_trash', False)
            }
            
            return extracted_data
            
        except Exception as e:
            self.logger.error(f"Ошибка извлечения полей: {e}")
            return {}
    
    def _extract_title(self, properties: Dict) -> str:
        """Извлечение заголовка"""
        for prop_name, prop_value in properties.items():
            if prop_value.get('type') == 'title':
                title_array = prop_value.get('title', [])
                if title_array:
                    return title_array[0].get('plain_text', '')
        return 'No Title'
    
    def _extract_rich_text(self, properties: Dict, prop_name: str) -> str:
        """Извлечение текста из rich_text свойства"""
        prop = properties.get(prop_name, {})
        if prop.get('type') == 'rich_text':
            rich_text_array = prop.get('rich_text', [])
            return ''.join([item.get('plain_text', '') for item in rich_text_array])
        return ''
    
    def _extract_status(self, properties: Dict, prop_name: str) -> str:
        """Извлечение статуса"""
        prop = properties.get(prop_name, {})
        if prop.get('type') == 'status' and prop.get('status'):
            return prop['status'].get('name', '')
        return ''
    
    def _extract_date(self, properties: Dict, prop_name: str) -> str:
        """Извлечение даты"""
        prop = properties.get(prop_name, {})
        if prop.get('type') == 'date' and prop.get('date'):
            return prop['date'].get('start', '')
        return ''
    
    def _extract_people(self, properties: Dict, prop_name: str) -> str:
        """Извлечение людей"""
        prop = properties.get(prop_name, {})
        if prop.get('type') == 'people':
            people_array = prop.get('people', [])
            if people_array:
                return people_array[0].get('name', '')
        return ''
    
    def _extract_multi_select(self, properties: Dict, prop_name: str) -> list:
        """Извлечение значений multi_select свойства"""
        prop = properties.get(prop_name, {})
        if prop.get('type') == 'multi_select':
            return [item.get('name', '') for item in prop.get('multi_select', [])]
        return []
    
    def _extract_relation(self, properties: Dict, prop_name: str) -> str:
        """Извлечение связи с получением названия"""
        prop = properties.get(prop_name, {})
        if prop.get('type') == 'relation':
            relation_array = prop.get('relation', [])
            if relation_array:
                related_id = relation_array[0].get('id', '')
                # Получаем название связанной страницы
                try:
                    related_data = notion_client.get_page_data(related_id)
                    if related_data:
                        related_title = self._extract_title(related_data.get('properties', {}))
                        return related_title if related_title else f"Related (ID: {related_id})"
                    else:
                        return f"Related (ID: {related_id})"
                except Exception as e:
                    self.logger.error(f"Ошибка получения названия связанного элемента: {e}")
                    return f"Related (ID: {related_id})"
        return ''
    
    def _extract_files(self, properties: Dict, prop_name: str) -> list:
        """Извлечение файлов"""
        prop = properties.get(prop_name, {})
        if prop.get('type') == 'files':
            files_array = prop.get('files', [])
            return [file.get('name', '') for file in files_array]
        return []
    
    def _extract_url(self, properties: Dict, prop_name: str) -> str:
        """Извлечение URL"""
        prop = properties.get(prop_name, {})
        if prop.get('type') == 'url' and prop.get('url'):
            return prop['url']
        return ''
    
    def _extract_created_time(self, page_data: Dict) -> str:
        """Извлечение времени создания"""
        created_time = page_data.get('created_time', '')
        if created_time:
            try:
                dt = datetime.fromisoformat(created_time.replace('Z', '+00:00'))
                return dt.strftime('%d.%m.%Y %H:%M')
            except:
                return created_time
        return ''
    
    def _extract_last_edited_time(self, page_data: Dict) -> str:
        """Извлечение времени последнего редактирования"""
        last_edited_time = page_data.get('last_edited_time', '')
        if last_edited_time:
            try:
                dt = datetime.fromisoformat(last_edited_time.replace('Z', '+00:00'))
                return dt.strftime('%d.%m.%Y %H:%M')
            except:
                return last_edited_time
        return ''
    
    def format_enhanced_telegram_message(self, data: Dict, change_type: str = "updated") -> str:
        """Форматирование улучшенного сообщения для Telegram с ВСЕМИ данными"""
        try:
            
            # Определяем тип события
            if change_type == "page.created":
                event_text = "🔔 <b>NEW TASK</b>"
            elif change_type == "page.properties_updated":
                event_text = "🔔 <b>TASK UPDATE</b>"
            else:
                event_text = "🔔 <b>TASK CHANGE</b>"
            
            message = f"{event_text}\n"
            if data.get('department'):
                message += f"🏢 <b>Department:</b> {data.get('department')}\n"
            if data.get('project'):
                message += f"📁 <b>Project:</b> {data.get('project')}\n"
            if data.get('tasks'):
                message += f"📋 <b>Tasks:</b> {data.get('tasks')}\n\n"

            

            message += f"📌 <b>Title:</b> {data.get('title', 'No Title')}\n"

            if data.get('description'):
                desc = data.get('description')
                message += f"📝 <b>Description:</b> {desc}\n\n"
            
            if data.get('status'):
                message += f"🔹 <b>Status:</b> {data.get('status')}\n"

            # Исполнитель
            if data.get('executor'):
                message += f"👤 <b>Executor:</b> {data.get('executor')}\n"
            
            # Назначил
            if data.get('assigned_by'):
                message += f"👨‍💼 <b>Assigned by:</b> {data.get('assigned_by')}\n"
            
            # Дедлайн
            if data.get('deadline'):
                message += f"⏰ <b>Deadline:</b> {data.get('deadline')}\n"
            
            # Telegram пользователи
            if data.get('telegram_username'):
                telegram_str = " ".join([f"{user}" for user in data.get('telegram_username', [])])
                message += f"📱 <b>Telegram:</b> {telegram_str}\n"

            # Ссылка
            if data.get('url'):
                message += f"\n🔗 <a href='{data.get('url')}'>Open in Notion</a>"
            
            return message
            
        except Exception as e:
            self.logger.error(f"Ошибка форматирования сообщения: {e}")
            return f"📝 Notion Update: {data.get('title', 'No Title')}"
    
    async def process_webhook_event(self, event_data: Dict[str, Any]) -> bool:
        """Обработка webhook события"""
        try:
            # Логируем полные данные события для отладки
            self.logger.info(f"Полные данные события: {json.dumps(event_data, indent=2)}")
            
            event_type = event_data.get('type')
            
            self.logger.info(f"Получено webhook событие: {event_type}")
            
            if not event_type:
                self.logger.warning("Отсутствует тип события")
                return False
            
            # ИСПРАВЛЕНО: Обрабатываем все события страниц через entity
            if event_type in ['page.created', 'page.updated', 'page.properties_updated']:
                # Новый формат события - все события используют entity
                entity = event_data.get('entity', {})
                entity_type = entity.get('type')
                page_id = entity.get('id')
                
                if entity_type == 'page' and page_id:
                    # Получаем database_id из данных события
                    database_id = None
                    if 'data' in event_data and 'parent' in event_data['data']:
                        parent_data = event_data['data']['parent']
                        if parent_data.get('type') == 'database':
                            database_id = parent_data.get('id')
                            self.logger.info(f"Found database_id in webhook data: {database_id}")
                    
                    if event_type == 'page.properties_updated':
                        updated_properties = event_data.get('data', {}).get('updated_properties', [])
                        self.logger.info(f"Обрабатываем страницу (новый формат): {page_id}, свойства: {updated_properties}")
                    else:
                        self.logger.info(f"Обрабатываем страницу (новый формат): {page_id}")
                    return await self._process_page_event(event_type, page_id, database_id)
                else:
                    self.logger.warning(f"Неверная структура entity: type={entity_type}, id={page_id}")
                    return False
            
            elif event_type == 'page.deleted':
                # Событие удаления страницы - пока не обрабатываем
                self.logger.info("Игнорируем событие удаления страницы")
                return False
            
            else:
                # Проверяем на верификационные токены
                if 'verification_token' in event_data:
                    self.logger.info("Получен верификационный токен - игнорируем")
                    return False
                
                self.logger.info(f"Игнорируем событие типа: {event_type}")
                return False
                
        except Exception as e:
            self.logger.error(f"Ошибка при обработке webhook события: {e}")
            return False
    
    async def _process_page_event(self, event_type: str, page_id: str, database_id: str = None) -> bool:
        """Обработка события страницы с полными данными"""
        try:
            # Получаем данные страницы из Notion
            page_data = notion_client.get_page_data(page_id)
            if not page_data:
                self.logger.warning(f"Не удалось получить данные страницы {page_id}")
                return False
            
            # Извлекаем ВСЕ поля с database_id
            extracted_data = self.extract_all_fields(page_data, database_id)
            self.logger.info(f"Извлеченные данные: {extracted_data}")
            
            # Форматируем улучшенное сообщение
            formatted_message = self.format_enhanced_telegram_message(extracted_data, event_type)
            
            # Создаем inline кнопки для изменения статуса
            reply_markup = None
            if page_id and notion_client:
                try:
                    # Получаем доступные статусы
                    self.logger.info(f"Получение опций статуса для страницы {page_id}...")
                    status_options = notion_client.get_page_status_options(page_id)
                    self.logger.info(f"Получены опции статуса: {status_options}")
                    
                    if status_options and len(status_options) > 0:
                        keyboard = []
                        # Группируем кнопки по 2 в ряд
                        for i in range(0, len(status_options), 2):
                            row = []
                            status1 = status_options[i]
                            callback1 = f"status:{page_id}:{status1}"
                            callback1_len = len(callback1.encode('utf-8'))
                            self.logger.info(f"Создаем кнопку: '{status1}' с callback: '{callback1}' (длина: {callback1_len} байт)")
                            
                            # Telegram ограничение: callback_data максимум 64 байта
                            if callback1_len > 64:
                                self.logger.warning(f"⚠️ Callback data слишком длинный ({callback1_len} > 64), обрезаем")
                                # Обрезаем статус, оставляя место для префикса
                                max_status_len = 64 - len(f"status:{page_id}:".encode('utf-8'))
                                status1_short = status1[:max_status_len]
                                callback1 = f"status:{page_id}:{status1_short}"
                                self.logger.warning(f"⚠️ Обрезанный callback: '{callback1}'")
                            
                            row.append(InlineKeyboardButton(
                                status1,
                                callback_data=callback1
                            ))
                            if i + 1 < len(status_options):
                                status2 = status_options[i + 1]
                                callback2 = f"status:{page_id}:{status2}"
                                callback2_len = len(callback2.encode('utf-8'))
                                self.logger.info(f"Создаем кнопку: '{status2}' с callback: '{callback2}' (длина: {callback2_len} байт)")
                                
                                if callback2_len > 64:
                                    self.logger.warning(f"⚠️ Callback data слишком длинный ({callback2_len} > 64), обрезаем")
                                    max_status_len = 64 - len(f"status:{page_id}:".encode('utf-8'))
                                    status2_short = status2[:max_status_len]
                                    callback2 = f"status:{page_id}:{status2_short}"
                                    self.logger.warning(f"⚠️ Обрезанный callback: '{callback2}'")
                                
                                row.append(InlineKeyboardButton(
                                    status2,
                                    callback_data=callback2
                                ))
                            keyboard.append(row)
                        
                        reply_markup = InlineKeyboardMarkup(keyboard)
                        self.logger.info(f"Создано {len(keyboard)} рядов кнопок для изменения статуса")
                    else:
                        self.logger.warning(f"Нет опций статуса для страницы {page_id}")
                except Exception as e:
                    self.logger.error(f"Ошибка при создании кнопок статуса: {e}", exc_info=True)
            
            # Отправляем в Telegram с полными данными и кнопками
            success = await telegram_client.send_custom_message(formatted_message, reply_markup=reply_markup)
            if success:
                self.logger.info(f"Событие {event_type} с полными данными успешно обработано для страницы {page_id}")
            else:
                self.logger.error(f"Ошибка при отправке полных данных в Telegram для страницы {page_id}")
            
            return success
            
        except Exception as e:
            self.logger.error(f"Ошибка при получении данных страницы {page_id}: {e}")
            return False

# Инициализация процессора
webhook_processor = WebhookProcessor()

# Обработчики Telegram сообщений
async def start_command(update: Update, context):
    """Обработчик команды /start"""
    try:
        logger.info(f"Получена команда /start от {update.message.from_user.username}")
        await update.message.reply_text(
            "Привет! Я бот для управления задачами в Notion.\n\n"
            "Как использовать:\n"
            "1. Когда приходит уведомление о задаче, используйте кнопки под сообщением для изменения статуса\n"
            "2. Или используйте команду: /status <page_id>\n\n"
            "Нажмите на кнопки статуса под сообщениями о задачах!"
        )
    except Exception as e:
        logger.error(f"Ошибка в start_command: {e}", exc_info=True)

async def handle_message(update: Update, context):
    """Обработчик текстовых сообщений"""
    try:
        text = update.message.text.strip()
        chat_id = update.message.chat_id
        
        logger.info(f"Получено сообщение от {chat_id}: {text}")
        
        # Если сообщение начинается с /status, обрабатываем команду
        if text.startswith('/status '):
            page_id = text.replace('/status ', '').strip()
            if page_id and notion_client:
                # Получаем доступные статусы
                status_options = notion_client.get_page_status_options(page_id)
                if status_options:
                    keyboard = []
                    for status in status_options:
                        keyboard.append([InlineKeyboardButton(
                            status, 
                            callback_data=f"status:{page_id}:{status}"
                        )])
                    
                    reply_markup = InlineKeyboardMarkup(keyboard)
                    await update.message.reply_text(
                        "Выберите новый статус:",
                        reply_markup=reply_markup
                    )
                else:
                    await update.message.reply_text("Не удалось получить список статусов")
            else:
                await update.message.reply_text("Использование: /status <page_id>")
        else:
            # Простое сообщение - создаем страницу в Notion
            await update.message.reply_text("Для изменения статуса используйте: /status <page_id>")
    except Exception as e:
        logger.error(f"Ошибка в handle_message: {e}")
        if update.message:
            await update.message.reply_text(f"Ошибка: {str(e)}")

async def handle_callback(update: Update, context):
    """Обработчик callback от inline кнопок"""
    global notion_client
    logger.info(f"🎯 ===== handle_callback ВЫЗВАН =====")
    logger.info(f"🎯 Update ID: {update.update_id}")
    logger.info(f"🎯 Context: {context}")
    try:
        if not update.callback_query:
            logger.error("❌ update.callback_query is None!")
            logger.error(f"❌ Update object: {update}")
            return
        
        query = update.callback_query
        if not query.data:
            logger.error("❌ query.data is None!")
            await query.answer("❌ Ошибка: нет данных в callback", show_alert=True)
            return
        
        data = query.data
        user = query.from_user
        
        logger.info(f"🔔 ===== CALLBACK RECEIVED =====")
        logger.info(f"🔔 Callback data: {data}")
        logger.info(f"🔔 От пользователя: {user.username or user.first_name if user else 'Unknown'} (ID: {user.id if user else 'N/A'})")
        logger.info(f"🔔 Update ID: {update.update_id}")
        logger.info(f"🔔 Message ID: {query.message.message_id if query.message else 'N/A'}")
        logger.info(f"🔔 =============================")
        
        # Проверяем доступность notion_client
        if notion_client is None:
            logger.error("❌ notion_client is None в handle_callback!")
            await query.answer("❌ Notion клиент не инициализирован", show_alert=True)
            return
        
        logger.info(f"✅ notion_client доступен: {type(notion_client)}")
        
        # Сначала отвечаем на callback (важно делать это сразу)
        try:
            await query.answer()
            logger.info("✅ Ответ на callback отправлен")
        except Exception as e:
            logger.error(f"Ошибка при отправке ответа на callback: {e}")
        
        if data.startswith('status:'):
            # Формат: status:page_id:status_name
            # Важно: status_name может содержать двоеточия, поэтому используем split с ограничением
            parts = data.split(':', 2)  # Разделяем максимум на 3 части
            if len(parts) == 3:
                page_id = parts[1]
                status_name = parts[2]  # Все что после второго двоеточия - это имя статуса
                
                logger.info(f"🔄 Обновление статуса для страницы {page_id} на '{status_name}'")
                logger.info(f"📋 Разобранный callback: page_id={page_id}, status_name={status_name}")
                
                if notion_client:
                    # Находим название свойства статуса
                    try:
                        page = notion_client.client.pages.retrieve(page_id=page_id)
                        properties = page.get('properties', {})
                        status_property_name = None
                        
                        for prop_name, prop_data in properties.items():
                            if prop_data.get('type') == 'status':
                                status_property_name = prop_name
                                break
                        
                        if status_property_name:
                            logger.info(f"Найдено свойство статуса: {status_property_name}")
                            
                            # Получаем доступные опции статуса для проверки
                            available_statuses = notion_client.get_page_status_options(page_id)
                            logger.info(f"📋 Доступные статусы: {available_statuses}")
                            logger.info(f"📋 Запрашиваемый статус: '{status_name}'")
                            
                            # Проверяем, что статус существует в опциях
                            if status_name not in available_statuses:
                                logger.warning(f"⚠️ Статус '{status_name}' не найден в доступных опциях!")
                                logger.warning(f"⚠️ Доступные опции: {available_statuses}")
                                # Пробуем найти похожий статус (без учета регистра)
                                status_lower = status_name.lower()
                                matching_status = None
                                for avail_status in available_statuses:
                                    if avail_status.lower() == status_lower:
                                        matching_status = avail_status
                                        logger.info(f"✅ Найден похожий статус (без учета регистра): '{matching_status}'")
                                        break
                                
                                if matching_status:
                                    status_name = matching_status
                                    logger.info(f"🔄 Используем статус: '{status_name}'")
                                else:
                                    await query.answer(f"❌ Статус '{status_name}' не найден", show_alert=True)
                                    return
                            
                            # Обновляем статус в Notion
                            logger.info(f"🔄 Обновление статуса в Notion: {status_property_name} = '{status_name}'")
                            success = notion_client.update_page_property(
                                page_id=page_id,
                                property_name=status_property_name,
                                property_value=status_name
                            )
                            
                            if success:
                                logger.info(f"Статус успешно обновлен в Notion: {status_name}")
                                
                                # Обновляем сообщение, если оно существует
                                if query.message:
                                    try:
                                        # Получаем текущее сообщение
                                        message_text = query.message.text or query.message.caption or ""
                                        
                                        # Обновляем статус в тексте сообщения
                                        updated_text = re.sub(
                                            r'🔹 <b>Status:</b> .+',
                                            f'🔹 <b>Status:</b> {status_name}',
                                            message_text
                                        )
                                        
                                        # Обновляем сообщение
                                        await query.edit_message_text(
                                            text=updated_text,
                                            parse_mode="HTML",
                                            reply_markup=query.message.reply_markup
                                        )
                                        
                                        logger.info(f"✅ Сообщение обновлено со статусом: {status_name}")
                                    except Exception as e:
                                        logger.error(f"Ошибка при обновлении сообщения: {e}", exc_info=True)
                                
                                # Отправляем подтверждение
                                await query.answer(f"✅ Статус изменен на: {status_name}", show_alert=False)
                            else:
                                logger.error("Не удалось обновить статус в Notion")
                                await query.answer("❌ Ошибка при обновлении статуса в Notion", show_alert=True)
                        else:
                            logger.warning("Свойство статуса не найдено")
                            await query.answer("❌ Свойство статуса не найдено", show_alert=True)
                    except Exception as e:
                        logger.error(f"Ошибка при обработке callback: {e}", exc_info=True)
                        await query.answer(f"❌ Ошибка: {str(e)}", show_alert=True)
                else:
                    logger.error("Notion клиент не инициализирован")
                    await query.answer("❌ Notion клиент не инициализирован", show_alert=True)
            else:
                logger.warning(f"⚠️ Неверный формат callback data: {data}")
                logger.warning(f"⚠️ Ожидался формат: status:page_id:status_name")
                logger.warning(f"⚠️ Получено частей после split: {len(parts)}")
                try:
                    await query.answer("❌ Неверный формат данных", show_alert=True)
                except Exception as e:
                    logger.error(f"Ошибка при отправке ответа: {e}")
        else:
            logger.warning(f"⚠️ Неизвестный тип callback: {data}")
            logger.warning(f"⚠️ Callback не начинается с 'status:'")
            try:
                await query.answer("❌ Неизвестная команда", show_alert=True)
            except Exception as e:
                logger.error(f"Ошибка при отправке ответа: {e}")
    except Exception as e:
        logger.error(f"❌ КРИТИЧЕСКАЯ ОШИБКА в handle_callback: {e}", exc_info=True)
        try:
            if update.callback_query:
                await update.callback_query.answer(f"❌ Ошибка: {str(e)[:50]}", show_alert=True)
        except Exception as e2:
            logger.error(f"Не удалось отправить ответ об ошибке: {e2}")

@app.on_event("startup")
async def startup_event():
    """Инициализация при запуске"""
    global notion_client, telegram_client, telegram_app
    
    try:
        notion_client = NotionIntegration(
            token=os.getenv('NOTION_TOKEN'),
            database_id=os.getenv('NOTION_DATABASE_ID')
        )
        logger.info("Notion клиент инициализирован")
    except Exception as e:
        logger.error(f"Ошибка инициализации Notion клиента: {e}")
    
    try:
        telegram_client = TelegramIntegration(
            bot_token=os.getenv('TELEGRAM_BOT_TOKEN'),
            channel_id=os.getenv('TELEGRAM_CHANNEL_ID')
        )
        logger.info("Telegram клиент инициализирован")
        
        # Инициализируем Telegram Application для обработки сообщений через webhook
        bot_token = os.getenv('TELEGRAM_BOT_TOKEN')
        if bot_token:
            global telegram_app
            telegram_app = Application.builder().token(bot_token).build()
            
            # Добавляем обработчики (важен порядок: CallbackQueryHandler должен быть перед MessageHandler)
            logger.info("Добавление обработчиков Telegram...")
            telegram_app.add_handler(CommandHandler("start", start_command))
            telegram_app.add_handler(CallbackQueryHandler(handle_callback))  # Важно: перед MessageHandler!
            telegram_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
            logger.info("✅ Обработчики Telegram добавлены: start_command, callback_query, handle_message")
            
            # Инициализируем и запускаем Application для webhook
            try:
                logger.info("Инициализация Telegram Application для webhook...")
                await telegram_app.initialize()
                await telegram_app.start()
                logger.info("✅ Telegram Application инициализирован для webhook")
                
                # Настраиваем webhook URL
                webhook_url = os.getenv('TELEGRAM_WEBHOOK_URL', 'https://kosmosvip.org/telegram/webhook')
                logger.info(f"Настройка webhook URL: {webhook_url}")
                
                # Устанавливаем webhook
                await telegram_app.bot.set_webhook(
                    url=webhook_url,
                    allowed_updates=['message', 'callback_query'],
                    drop_pending_updates=True
                )
                logger.info(f"✅ Telegram webhook настроен: {webhook_url}")
                
                # Проверяем информацию о webhook
                webhook_info = await telegram_app.bot.get_webhook_info()
                logger.info(f"Webhook info: {webhook_info}")
            except Exception as e:
                logger.error(f"Ошибка при настройке Telegram webhook: {e}", exc_info=True)
    except Exception as e:
        logger.error(f"Ошибка инициализации Telegram клиента: {e}")

@app.get("/")
async def root():
    """Корневой endpoint для проверки работы"""
    return {"message": "Notion-Telegram Webhook Server - SEPARATED HIERARCHY", "status": "running"}

@app.get("/health")
async def health_check():
    """Проверка здоровья сервера"""
    return {
        "status": "healthy",
        "telegram": "ok" if telegram_client else "error",
        "timestamp": datetime.now().isoformat()
    }

@app.get("/test/notion-webhook")
async def test_notion_webhook():
    """Тестовый endpoint для проверки доступности /notion-webhook"""
    return {
        "status": "ok",
        "message": "Endpoint /notion-webhook доступен",
        "test_url": "/notion-webhook?verification=test_token",
        "timestamp": datetime.now().isoformat()
    }

@app.get("/webhook/notion")
async def webhook_verification(challenge: str = None, verification: str = None):
    """Обработка запросов верификации на /webhook/notion"""
    # Notion может отправлять параметр как "challenge" или "verification"
    token = challenge or verification
    if token:
        logger.info(f"🔍 GET /webhook/notion - Получен токен для верификации: {token}")
        response_data = {"challenge": token}
        logger.info(f"📤 Отправляем ответ: {response_data}")
        return JSONResponse(content=response_data, headers={"Content-Type": "application/json"})
    logger.warning("⚠️ GET /webhook/notion - Запрос без токена")
    return JSONResponse(
        content={"status": "error", "message": "no challenge provided"},
        headers={"Content-Type": "application/json"}
    )

@app.options("/notion-webhook")
async def notion_webhook_options():
    """Обработка OPTIONS запросов для CORS"""
    return JSONResponse(
        content={"status": "ok"},
        headers={
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
            "Access-Control-Allow-Headers": "*",
        }
    )

@app.get("/notion-webhook")
async def notion_webhook_verification(request: Request):
    """Обработка верификации webhook от Notion на /notion-webhook"""
    try:
        # Логируем все query параметры
        all_params = dict(request.query_params)
        logger.info(f"🔍 GET /notion-webhook - Все query параметры: {all_params}")
        
        # Notion может отправлять параметр как "verification" или "challenge"
        verification_token = request.query_params.get("verification") or request.query_params.get("challenge")
        
        if verification_token:
            logger.info(f"✅ === NOTION VERIFICATION REQUEST ===")
            logger.info(f"Token: {verification_token}")
            logger.info(f"Time: {datetime.now()}")
            logger.info(f"Full URL: {request.url}")
            logger.info(f"IP: {request.client.host if request.client else 'Unknown'}")
            logger.info(f"Headers: {dict(request.headers)}")
            logger.info(f"====================================")
            
            # Notion ожидает получить токен обратно в ответе в формате {"challenge": token}
            response_data = {"challenge": verification_token}
            logger.info(f"📤 Отправляем ответ: {response_data}")
            
            # Явно возвращаем JSONResponse с правильным содержимым
            return JSONResponse(
                content=response_data,
                headers={"Content-Type": "application/json"}
            )
        
        logger.warning(f"⚠️ Верификационный запрос без токена. Query params: {all_params}")
        return JSONResponse(
            status_code=400,
            content={"status": "error", "message": "no verification token provided"},
            headers={"Content-Type": "application/json"}
        )
    except Exception as e:
        logger.error(f"❌ Ошибка при обработке верификации: {e}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={"status": "error", "message": str(e)},
            headers={"Content-Type": "application/json"}
        )

@app.post("/notion-webhook")
async def notion_webhook_post(request: Request, background_tasks: BackgroundTasks):
    """Обработка POST запросов от Notion на /notion-webhook"""
    try:
        # Получаем тело запроса
        body = await request.body()
        
        # Логируем сырые данные
        logger.info(f"Получены POST данные на /notion-webhook: {body}")
        
        # Получаем подпись
        signature = request.headers.get('notion-signature', '')
        
        # Проверяем подпись
        if not webhook_processor.verify_signature(body, signature):
            logger.warning("Неверная подпись webhook")
            raise HTTPException(status_code=401, detail="Unauthorized")
        
        # Парсим JSON
        try:
            event_data = json.loads(body.decode('utf-8'))
        except json.JSONDecodeError as e:
            logger.error(f"Ошибка парсинга JSON: {e}")
            raise HTTPException(status_code=400, detail="Invalid JSON")
        
        logger.info("Webhook событие принято на /notion-webhook")
        
        # Обрабатываем событие в фоне
        background_tasks.add_task(webhook_processor.process_webhook_event, event_data)
        
        return {"status": "ok", "message": "Event processed"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Ошибка при обработке webhook: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@app.post("/")
async def webhook_root(request: Request, background_tasks: BackgroundTasks):
    """Обработка webhook событий на корневом URL"""
    try:
        # Получаем тело запроса
        body = await request.body()
        
        # Логируем сырые данные
        logger.info(f"Получены сырые данные: {body}")
        
        # Получаем подпись
        signature = request.headers.get('notion-signature', '')
        
        # Проверяем подпись
        if not webhook_processor.verify_signature(body, signature):
            logger.warning("Неверная подпись webhook")
            raise HTTPException(status_code=401, detail="Unauthorized")
        
        # Парсим JSON
        try:
            event_data = json.loads(body.decode('utf-8'))
        except json.JSONDecodeError as e:
            logger.error(f"Ошибка парсинга JSON: {e}")
            raise HTTPException(status_code=400, detail="Invalid JSON")
        
        logger.info("Webhook событие принято на корневом URL")
        
        # Обрабатываем событие в фоне
        background_tasks.add_task(webhook_processor.process_webhook_event, event_data)
        
        return {"status": "ok", "message": "Event processed"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Ошибка при обработке webhook: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@app.post("/test/send")
async def test_send(request: Request):
    """Тестовая отправка сообщения"""
    try:
        data = await request.json()
        message = data.get('message', 'Test webhook with separated hierarchy')
        
        if telegram_client:
            success = await telegram_client.send_custom_message(message)
            if success:
                return {"status": "ok", "message": "Message sent"}
            else:
                return {"status": "error", "message": "Failed to send message"}
        else:
            return {"status": "error", "message": "Telegram client not initialized"}
            
    except Exception as e:
        logger.error(f"Ошибка при тестовой отправке: {e}")
        return {"status": "error", "message": str(e)}

@app.post("/telegram/webhook")
async def telegram_webhook(request: Request):
    """Обработка webhook обновлений от Telegram"""
    try:
        if not telegram_app:
            logger.error("Telegram Application не инициализирован")
            return JSONResponse(
                status_code=503,
                content={"status": "error", "message": "Telegram application not initialized"}
            )
        
        # Получаем сырое тело запроса
        body = await request.body()
        logger.info(f"📥 Получен запрос от Telegram, размер: {len(body)} байт")
        
        if not body:
            logger.warning("Пустое тело запроса от Telegram")
            return JSONResponse(content={"status": "ok"})
        
        # Парсим JSON
        try:
            data = json.loads(body.decode('utf-8'))
        except json.JSONDecodeError as e:
            logger.error(f"Ошибка парсинга JSON от Telegram: {e}, тело: {body[:200]}")
            return JSONResponse(
                status_code=400,
                content={"status": "error", "message": "Invalid JSON"}
            )
        
        update_id = data.get('update_id')
        update_type = None
        if 'callback_query' in data:
            update_type = 'callback_query'
            callback_query_data = data.get('callback_query', {})
            callback_data = callback_query_data.get('data', 'N/A')
            message_info = callback_query_data.get('message', {})
            message_id = message_info.get('message_id', 'N/A')
            from_user = callback_query_data.get('from', {})
            user_info = f"{from_user.get('username', '')} ({from_user.get('id', 'N/A')})"
            
            logger.info(f"🔔 ===== CALLBACK_QUERY RECEIVED =====")
            logger.info(f"🔔 Update ID: {update_id}")
            logger.info(f"🔔 Callback data: {callback_data}")
            logger.info(f"🔔 Message ID: {message_id}")
            logger.info(f"🔔 От пользователя: {user_info}")
            logger.info(f"🔔 Полные данные callback_query: {json.dumps(callback_query_data, indent=2, ensure_ascii=False)}")
            logger.info(f"🔔 =====================================")
        elif 'message' in data:
            update_type = 'message'
            logger.info(f"📥 Получено обновление от Telegram: update_id={update_id}, тип=message")
        else:
            logger.info(f"📥 Получено обновление от Telegram: update_id={update_id}, тип=unknown, keys={list(data.keys())}")
            logger.info(f"📥 Полные данные: {json.dumps(data, indent=2, ensure_ascii=False)}")
        
        # Создаем объект Update из данных
        try:
            update = Update.de_json(data, telegram_app.bot)
            if not update:
                logger.warning(f"Не удалось создать объект Update из данных: {data}")
                return JSONResponse(content={"status": "ok"})
            
            # Проверяем тип обновления
            if update.callback_query:
                logger.info(f"🔔 Update объект содержит callback_query: {update.callback_query.data}")
                logger.info(f"🔔 Callback query ID: {update.callback_query.id}")
                logger.info(f"🔔 Message: {update.callback_query.message.message_id if update.callback_query.message else 'N/A'}")
            elif update.message:
                logger.info(f"💬 Обнаружено message: {update.message.text}")
            
            # Обрабатываем обновление через Application
            logger.info(f"🔄 Передаем обновление в Application.process_update...")
            try:
                await telegram_app.process_update(update)
                logger.info(f"✅ Обновление {update.update_id} успешно обработано через Application")
            except Exception as e:
                logger.error(f"❌ Ошибка при обработке обновления через Application: {e}", exc_info=True)
                raise
            
            return JSONResponse(content={"status": "ok"})
            
        except Exception as e:
            logger.error(f"Ошибка при обработке обновления Telegram: {e}", exc_info=True)
            # Все равно возвращаем 200, чтобы Telegram не повторял запрос
            return JSONResponse(content={"status": "ok"})
            
    except Exception as e:
        logger.error(f"Критическая ошибка при обработке Telegram webhook: {e}", exc_info=True)
        # Возвращаем 200, чтобы Telegram не повторял запрос
        return JSONResponse(content={"status": "ok"})

@app.on_event("shutdown")
async def shutdown_event():
    """Остановка при завершении"""
    global telegram_app
    if telegram_app:
        try:
            # Удаляем webhook
            logger.info("Удаление Telegram webhook...")
            await telegram_app.bot.delete_webhook(drop_pending_updates=False)
            
            # Останавливаем Application
            await telegram_app.stop()
            await telegram_app.shutdown()
            logger.info("✅ Telegram bot остановлен")
        except Exception as e:
            logger.error(f"Ошибка при остановке Telegram bot: {e}", exc_info=True)

if __name__ == "__main__":
    host = os.getenv('WEBHOOK_HOST', '0.0.0.0')
    port = int(os.getenv('WEBHOOK_PORT', 8000))
    logger.info(f"Запуск webhook сервера с разделенной иерархией на {host}:{port}")
    uvicorn.run(
        "webhook_server_fixed_properties:app",
        host=host,
        port=port,
        reload=False,
        log_level="info"
    )
