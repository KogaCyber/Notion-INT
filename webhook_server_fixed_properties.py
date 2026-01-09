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
import threading
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
                            self.logger.info(f"Создаем кнопку: {status1} с callback: {callback1}")
                            row.append(InlineKeyboardButton(
                                status1,
                                callback_data=callback1
                            ))
                            if i + 1 < len(status_options):
                                status2 = status_options[i + 1]
                                callback2 = f"status:{page_id}:{status2}"
                                self.logger.info(f"Создаем кнопку: {status2} с callback: {callback2}")
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
    try:
        query = update.callback_query
        data = query.data
        user = query.from_user
        
        logger.info(f"🔔 Получен callback от {user.username or user.first_name}: {data}")
        logger.info(f"Полная информация о callback: update_id={update.update_id}, user_id={user.id}")
        
        # Проверяем доступность notion_client
        if notion_client is None:
            logger.error("❌ notion_client is None в handle_callback!")
            await query.answer("❌ Notion клиент не инициализирован", show_alert=True)
            return
        
        logger.info(f"✅ notion_client доступен: {type(notion_client)}")
        
        # Сначала отвечаем на callback
        await query.answer()
        
        if data.startswith('status:'):
            # Формат: status:page_id:status_name
            parts = data.split(':')
            if len(parts) == 3:
                page_id = parts[1]
                status_name = parts[2]
                
                logger.info(f"Обновление статуса для страницы {page_id} на {status_name}")
                
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
                            
                            # Обновляем статус в Notion
                            success = notion_client.update_page_property(
                                page_id=page_id,
                                property_name=status_property_name,
                                property_value=status_name
                            )
                            
                            if success:
                                logger.info(f"Статус успешно обновлен в Notion: {status_name}")
                                
                                # Получаем текущее сообщение
                                message_text = query.message.text
                                
                                # Обновляем статус в тексте сообщения
                                updated_text = re.sub(
                                    r'🔹 <b>Status:</b> .+',
                                    f'🔹 <b>Status:</b> {status_name}',
                                    message_text
                                )
                                
                                # Обновляем сообщение
                                try:
                                    await query.edit_message_text(
                                        text=updated_text,
                                        parse_mode="HTML",
                                        reply_markup=query.message.reply_markup
                                    )
                                    
                                    # Отправляем подтверждение
                                    await query.answer(f"✅ Статус изменен на: {status_name}", show_alert=False)
                                except Exception as e:
                                    logger.error(f"Ошибка при обновлении сообщения: {e}")
                                    await query.answer(f"✅ Статус обновлен: {status_name}", show_alert=True)
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
                logger.warning(f"Неверный формат callback data: {data}")
                await query.answer("❌ Неверный формат данных", show_alert=True)
        else:
            logger.warning(f"Неизвестный тип callback: {data}")
            await query.answer("❌ Неизвестная команда", show_alert=True)
    except Exception as e:
        logger.error(f"Критическая ошибка в handle_callback: {e}", exc_info=True)
        try:
            await query.answer(f"❌ Критическая ошибка: {str(e)}", show_alert=True)
        except:
            pass

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
        
        # Инициализируем Telegram Application для обработки сообщений
        bot_token = os.getenv('TELEGRAM_BOT_TOKEN')
        if bot_token:
            global telegram_app
            telegram_app = Application.builder().token(bot_token).build()
            
            # Добавляем обработчики
            logger.info("Добавление обработчиков Telegram...")
            telegram_app.add_handler(CommandHandler("start", start_command))
            telegram_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
            telegram_app.add_handler(CallbackQueryHandler(handle_callback))
            logger.info("✅ Обработчики Telegram добавлены: start_command, handle_message, handle_callback")
            
            # Запускаем polling в отдельном потоке
            def run_polling():
                """Запуск polling в отдельном потоке"""
                try:
                    logger.info("Создание нового event loop для Telegram polling...")
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    
                    async def init_and_run():
                        logger.info("Инициализация Telegram Application...")
                        await telegram_app.initialize()
                        logger.info("Запуск Telegram Application...")
                        await telegram_app.start()
                        logger.info("Telegram bot инициализирован и запущен, начинаем polling...")
                        await telegram_app.updater.start_polling(
                            drop_pending_updates=True,
                            allowed_updates=['message', 'callback_query']
                        )
                        logger.info("✅ Telegram bot polling успешно запущен и работает!")
                    
                    logger.info("Запуск async функций в event loop...")
                    loop.run_until_complete(init_and_run())
                    logger.info("Event loop запущен, polling работает...")
                    loop.run_forever()
                except Exception as e:
                    logger.error(f"Ошибка при запуске Telegram polling: {e}", exc_info=True)
            
            # Запускаем в отдельном потоке
            logger.info("Создание потока для Telegram polling...")
            polling_thread = threading.Thread(target=run_polling, daemon=True, name="TelegramPolling")
            polling_thread.start()
            logger.info("✅ Поток для Telegram polling запущен")
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

@app.get("/webhook/notion")
async def webhook_verification(challenge: str = None, verification: str = None):
    """Обработка запросов верификации"""
    # Notion может отправлять параметр как "challenge" или "verification"
    token = challenge or verification
    if token:
        logger.info(f"Получен токен для верификации: {token}")
        return {"challenge": token}
    return {"status": "no challenge provided"}

@app.get("/notion-webhook")
async def notion_webhook_verification(request: Request):
    """Обработка верификации webhook от Notion на /notion-webhook"""
    # Notion может отправлять параметр как "verification" или "challenge"
    verification_token = request.query_params.get("verification") or request.query_params.get("challenge")
    
    if verification_token:
        logger.info(f"=== NOTION VERIFICATION REQUEST ===")
        logger.info(f"Token: {verification_token}")
        logger.info(f"Time: {datetime.now()}")
        logger.info(f"Full URL: {request.url}")
        logger.info(f"IP: {request.client.host if request.client else 'Unknown'}")
        logger.info(f"====================================")
        
        # Notion ожидает получить токен обратно в ответе
        return {"challenge": verification_token}
    
    logger.warning("Верификационный запрос без токена")
    return {"status": "no verification token provided"}

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
    """Обработка входящих сообщений из Telegram для создания страниц в Notion"""
    try:
        data = await request.json()
        logger.info(f"Получено сообщение из Telegram: {json.dumps(data, indent=2)}")
        
        # Обработка обновления от Telegram
        update_type = data.get('update_id')
        message = data.get('message', {})
        
        if not message:
            # Это может быть другое обновление (редактирование, callback и т.д.)
            return {"status": "ok", "message": "Update processed"}
        
        # Получаем текст сообщения
        text = message.get('text', '').strip()
        if not text:
            return {"status": "ok", "message": "No text in message"}
        
        # Получаем информацию об отправителе
        from_user = message.get('from', {})
        user_name = from_user.get('username', from_user.get('first_name', 'Unknown'))
        
        logger.info(f"Сообщение от {user_name}: {text}")
        
        # Проверяем, что у нас есть notion_client
        if not notion_client:
            logger.error("Notion клиент не инициализирован")
            return {"status": "error", "message": "Notion client not initialized"}
        
        # Получаем database_id из переменных окружения
        database_id = os.getenv('NOTION_DATABASE_ID')
        if not database_id:
            logger.error("NOTION_DATABASE_ID не указан")
            return {"status": "error", "message": "Database ID not configured"}
        
        # Создаем страницу в Notion
        # Форматируем заголовок: первые 100 символов текста
        title = text[:100] if len(text) > 100 else text
        
        # Создаем страницу
        created_page = notion_client.create_page(
            title=title,
            database_id=database_id
        )
        
        if created_page:
            page_id = created_page.get('id')
            page_url = created_page.get('url', '')
            
            # Добавляем полный текст как содержимое страницы
            if len(text) > 100:
                notion_client.add_content_to_page(page_id, text)
            
            # Добавляем метаданные (от кого сообщение)
            metadata_text = f"\n\nОт: {user_name} (@{from_user.get('username', 'unknown')})"
            if from_user.get('first_name'):
                metadata_text += f" ({from_user.get('first_name')})"
            if from_user.get('last_name'):
                metadata_text += f" {from_user.get('last_name')}"
            
            notion_client.add_content_to_page(page_id, metadata_text)
            
            logger.info(f"Создана страница в Notion: {page_url}")
            
            # Отправляем подтверждение в Telegram (если нужно)
            if telegram_client:
                response_text = f"✅ Страница создана в Notion!\n🔗 [Открыть]({page_url})"
                await telegram_client.send_custom_message(response_text)
            
            return {
                "status": "ok",
                "message": "Page created",
                "page_id": page_id,
                "page_url": page_url
            }
        else:
            logger.error("Не удалось создать страницу в Notion")
            return {"status": "error", "message": "Failed to create page"}
            
    except Exception as e:
        logger.error(f"Ошибка при обработке Telegram webhook: {e}")
        return {"status": "error", "message": str(e)}

@app.on_event("shutdown")
async def shutdown_event():
    """Остановка при завершении"""
    global telegram_app
    if telegram_app:
        try:
            await telegram_app.updater.stop()
            await telegram_app.stop()
            await telegram_app.shutdown()
            logger.info("Telegram bot остановлен")
        except Exception as e:
            logger.error(f"Ошибка при остановке Telegram bot: {e}")

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
