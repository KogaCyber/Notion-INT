import logging
import asyncio
from typing import Dict, List, Optional
from telegram import Bot
from telegram.constants import ParseMode
from telegram.error import TelegramError

class TelegramIntegration:
    def __init__(self, bot_token: str, channel_id: str):
        """
        Инициализация Telegram Bot
        
        Args:
            bot_token: Токен Telegram бота
            channel_id: ID канала или username (@channel_name)
        """
        self.bot = Bot(token=bot_token)
        self.channel_id = channel_id
        self.logger = logging.getLogger(__name__)
        
    async def send_notion_item(self, item: Dict) -> bool:
        """
        Отправка элемента Notion в Telegram канал
        
        Args:
            item: Элемент из Notion базы данных
            
        Returns:
            True если сообщение отправлено успешно
        """
        try:
            message = self._format_notion_item(item)
            
            await self.bot.send_message(
                chat_id=self.channel_id,
                text=message,
                parse_mode=None,  # Отключаем Markdown для избежания ошибок
                disable_web_page_preview=False
            )
            
            self.logger.info(f"Сообщение отправлено в канал: {item.get('title', 'Без названия')}")
            return True
            
        except TelegramError as e:
            self.logger.error(f"Ошибка Telegram при отправке сообщения: {e}")
            return False
        except Exception as e:
            self.logger.error(f"Общая ошибка при отправке сообщения: {e}")
            return False
    
    async def send_multiple_items(self, items: List[Dict]) -> int:
        """
        Отправка нескольких элементов в канал
        
        Args:
            items: Список элементов из Notion
            
        Returns:
            Количество успешно отправленных сообщений
        """
        sent_count = 0
        
        for item in items:
            success = await self.send_notion_item(item)
            if success:
                sent_count += 1
            
            # Небольшая задержка между сообщениями
            await asyncio.sleep(1)
        
        self.logger.info(f"Отправлено {sent_count} из {len(items)} сообщений")
        return sent_count
    
    def _format_notion_item(self, item: Dict) -> str:
        """
        Форматирование элемента Notion для отправки в Telegram
        
        Args:
            item: Элемент из Notion
            
        Returns:
            Отформатированное сообщение
        """
        title = self._escape_markdown(item.get('title', 'Без названия'))
        status = item.get('status')
        tags = item.get('tags', [])
        url = item.get('url', '')
        created_time = item.get('created_time', '')
        
        # Форматирование даты
        formatted_date = self._format_date(created_time)
        
        # Построение сообщения
        message_parts = [f"📝 *{title}*"]
        
        if status:
            status_emoji = self._get_status_emoji(status)
            message_parts.append(f"{status_emoji} Статус: _{self._escape_markdown(status)}_")
        
        if tags:
            tags_text = " ".join([f"#{self._escape_markdown(tag)}" for tag in tags])
            message_parts.append(f"🏷️ {tags_text}")
        
        if formatted_date:
            message_parts.append(f"📅 {formatted_date}")
        
        if url:
            message_parts.append(f"🔗 [Открыть в Notion]({url})")
        
        return "\n\n".join(message_parts)
    
    def _escape_markdown(self, text: str) -> str:
        """
        Экранирование специальных символов для Markdown V2
        
        Args:
            text: Исходный текст
            
        Returns:
            Экранированный текст
        """
        if not text:
            return ""
        
        # Символы, которые нужно экранировать в Markdown V2
        escape_chars = ['_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']
        
        for char in escape_chars:
            text = text.replace(char, f"\\{char}")
        
        return text
    
    def _get_status_emoji(self, status: str) -> str:
        """
        Получение эмодзи для статуса
        
        Args:
            status: Статус элемента
            
        Returns:
            Соответствующий эмодзи
        """
        status_emojis = {
            'not started': '⏳',
            'in progress': '🔄',
            'completed': '✅',
            'cancelled': '❌',
            'on hold': '⏸️',
            'review': '👀',
            'published': '🚀',
            'draft': '📝'
        }
        
        return status_emojis.get(status.lower(), '📌')
    
    def _format_date(self, date_string: str) -> str:
        """
        Форматирование даты для отображения
        
        Args:
            date_string: Строка с датой в ISO формате
            
        Returns:
            Отформатированная дата
        """
        if not date_string:
            return ""
        
        try:
            from datetime import datetime
            dt = datetime.fromisoformat(date_string.replace('Z', '+00:00'))
            return dt.strftime("%d.%m.%Y %H:%M")
        except:
            return date_string
    
    async def send_custom_message(self, message: str, reply_markup=None) -> bool:
        """
        Отправка произвольного сообщения в канал
        
        Args:
            message: Текст сообщения
            reply_markup: Inline клавиатура (опционально)
            
        Returns:
            True если сообщение отправлено успешно
        """
        try:
            await self.bot.send_message(
                chat_id=self.channel_id,
                text=message,
                parse_mode="HTML",
                reply_markup=reply_markup
            )
            
            self.logger.info("Пользовательское сообщение отправлено")
            return True
            
        except TelegramError as e:
            self.logger.error(f"Ошибка при отправке пользовательского сообщения: {e}")
            return False
    
    async def test_connection(self) -> bool:
        """
        Тестирование подключения к Telegram
        
        Returns:
            True если подключение работает
        """
        try:
            bot_info = await self.bot.get_me()
            self.logger.info(f"Подключение к Telegram успешно. Бот: {bot_info.username}")
            return True
        except Exception as e:
            self.logger.error(f"Ошибка подключения к Telegram: {e}")
            return False 