import os
import logging
from datetime import datetime, timezone
from typing import List, Dict, Optional
from notion_client import Client

class NotionIntegration:
    def __init__(self, token: str, database_id: str):
        """
        Инициализация клиента Notion
        
        Args:
            token: Токен интеграции Notion
            database_id: ID базы данных Notion
        """
        self.client = Client(auth=token)
        self.database_id = database_id
        self.logger = logging.getLogger(__name__)
        
    def get_database_items(self, filter_new_only: bool = True) -> List[Dict]:
        """
        Получение элементов из базы данных Notion
        
        Args:
            filter_new_only: Если True, получает только новые элементы (созданные сегодня)
            
        Returns:
            Список элементов базы данных
        """
        try:
            query_filter = {}
            
            if filter_new_only:
                today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
                query_filter = {
                    "property": "Created time",
                    "created_time": {
                        "on_or_after": today
                    }
                }
            
            response = self.client.databases.query(
                database_id=self.database_id,
                
            )
            
            items = []
            for page in response['results']:
                item = self._parse_page(page)
                if item:
                    items.append(item)
                    
            self.logger.info(f"Получено {len(items)} элементов из Notion")
            return items
            
        except Exception as e:
            self.logger.error(f"Ошибка при получении данных из Notion: {e}")
            return []
    
    def _parse_page(self, page: Dict) -> Optional[Dict]:
        """
        Парсинг страницы Notion в структурированный объект
        
        Args:
            page: Объект страницы из Notion API
            
        Returns:
            Словарь с данными страницы
        """
        try:
            properties = page.get('properties', {})
            
            # Извлечение основных свойств
            title = self._extract_title(properties)
            status = self._extract_select(properties, 'Status')
            tags = self._extract_multi_select(properties, 'Tags')
            created_time = page.get('created_time')
            url = page.get('url')
            
            return {
                'id': page['id'],
                'title': title,
                'status': status,
                'tags': tags,
                'created_time': created_time,
                'url': url,
                'properties': properties
            }
            
        except Exception as e:
            self.logger.error(f"Ошибка при парсинге страницы: {e}")
            return None
    
    def _extract_title(self, properties: Dict) -> str:
        """Извлечение заголовка из свойств"""
        for prop_name, prop_value in properties.items():
            if prop_value.get('type') == 'title':
                title_array = prop_value.get('title', [])
                if title_array:
                    return title_array[0].get('plain_text', '')
        return 'Без названия'
    
    def _extract_select(self, properties: Dict, prop_name: str) -> Optional[str]:
        """Извлечение значения select свойства"""
        prop = properties.get(prop_name, {})
        if prop.get('type') == 'select' and prop.get('select'):
            return prop['select'].get('name')
        return None
    
    def _extract_multi_select(self, properties: Dict, prop_name: str) -> List[str]:
        """Извлечение значений multi_select свойства"""
        prop = properties.get(prop_name, {})
        if prop.get('type') == 'multi_select':
            return [item.get('name', '') for item in prop.get('multi_select', [])]
        return []
    
    def _extract_rich_text(self, properties: Dict, prop_name: str) -> str:
        """Извлечение текста из rich_text свойства"""
        prop = properties.get(prop_name, {})
        if prop.get('type') == 'rich_text':
            rich_text_array = prop.get('rich_text', [])
            return ''.join([item.get('plain_text', '') for item in rich_text_array])
        return ''
    
    def get_page_content(self, page_id: str) -> str:
        """
        Получение содержимого страницы Notion
        
        Args:
            page_id: ID страницы
            
        Returns:
            Текстовое содержимое страницы
        """
        try:
            response = self.client.blocks.children.list(block_id=page_id)
            content_parts = []
            
            for block in response['results']:
                block_text = self._extract_block_text(block)
                if block_text:
                    content_parts.append(block_text)
            
            return '\n'.join(content_parts)
            
        except Exception as e:
            self.logger.error(f"Ошибка при получении содержимого страницы: {e}")
            return ""
    
    def _extract_block_text(self, block: Dict) -> str:
        """Извлечение текста из блока"""
        block_type = block.get('type', '')
        
        text_blocks = ['paragraph', 'heading_1', 'heading_2', 'heading_3', 'bulleted_list_item', 'numbered_list_item']
        
        if block_type in text_blocks:
            rich_text = block.get(block_type, {}).get('rich_text', [])
            return ''.join([item.get('plain_text', '') for item in rich_text])
        
        return '' 
    def get_page_data(self, page_id: str) -> Optional[Dict]:
        """
        Получение данных страницы по ID
        
        Args:
            page_id: ID страницы в Notion
            
        Returns:
            Данные страницы или None при ошибке
        """
        try:
            # Получаем данные страницы
            page = self.client.pages.retrieve(page_id=page_id)
            
            # Парсим страницу
            parsed_page = self._parse_page(page)
            
            if parsed_page:
                self.logger.info(f"Получены данные страницы: {page_id}")
                return parsed_page
            else:
                self.logger.warning(f"Не удалось распарсить страницу: {page_id}")
                return None
                
        except Exception as e:
            self.logger.error(f"Ошибка при получении данных страницы {page_id}: {e}")
            return None
