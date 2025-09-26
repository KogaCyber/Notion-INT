# Notion-Telegram Интеграция

Автоматическая синхронизация данных между базой данных Notion и Telegram каналом.

## 🚀 Возможности

- ✅ **Webhooks в реальном времени** - мгновенная синхронизация при изменениях в Notion
- ✅ Автоматическое получение данных из базы Notion
- ✅ Форматированная отправка в Telegram канал  
- ✅ Настраиваемый интервал синхронизации (polling режим)
- ✅ Фильтрация только новых элементов
- ✅ Красивое форматирование сообщений с эмодзи
- ✅ Поддержка статусов, тегов и ссылок
- ✅ Полное логирование всех операций
- ✅ FastAPI webhook сервер с проверкой подписей

## 📋 Требования

- Python 3.8+
- Notion аккаунт с API токеном
- Telegram бот с доступом к каналу

## ⚙️ Установка

1. **Клонирование репозитория:**
```bash
git clone <repository-url>
cd notion-telegram-integration
```

2. **Установка зависимостей:**
```bash
pip install -r requirements.txt
```

3. **Настройка переменных окружения:**
```bash
cp config.example.env .env
```

## 🔧 Настройка

### 1. Настройка Notion

1. Перейдите на [https://www.notion.so/my-integrations](https://www.notion.so/my-integrations)
2. Создайте новую интеграцию
3. Скопируйте "Internal Integration Token"
4. Дайте интеграции доступ к нужной базе данных:
   - Откройте базу данных в Notion
   - Нажмите "Share" → "Invite"
   - Найдите вашу интеграцию и добавьте её

5. Скопируйте ID базы данных из URL:
   ```
   https://www.notion.so/workspace/DATABASE_ID?v=...
   ```

### 2. Настройка Telegram

1. Создайте бота через [@BotFather](https://t.me/botfather)
2. Получите токен бота
3. Добавьте бота в канал как администратора
4. Получите ID канала:
   - Для публичного: `@channel_username`
   - Для приватного: числовой ID (можно получить через [@userinfobot](https://t.me/userinfobot))

### 3. Заполнение .env файла

```env
# Notion API настройки
NOTION_TOKEN=your_notion_integration_token_here
NOTION_DATABASE_ID=your_notion_database_id_here
NOTION_WEBHOOK_SECRET=your_webhook_secret_here

# Telegram Bot настройки  
TELEGRAM_BOT_TOKEN=your_telegram_bot_token_here
TELEGRAM_CHANNEL_ID=@your_channel_username_or_chat_id

# Webhook сервер настройки (для webhook режима)
WEBHOOK_HOST=0.0.0.0
WEBHOOK_PORT=8000
WEBHOOK_URL=https://your-domain.com/webhook/notion

# Настройки синхронизации (для polling режима)
SYNC_INTERVAL_MINUTES=30
CHECK_NEW_ITEMS_ONLY=true
```

### 4. Настройка Webhook режима (рекомендуется)

Webhook режим обеспечивает мгновенные уведомления вместо постоянного опроса API.

**Требования:**
- Публично доступный сервер с HTTPS
- Открытый порт (по умолчанию 8000)

**Шаги настройки:**

1. **Настройте домен/сервер:**
   ```bash
   # Обновите WEBHOOK_URL в .env файле
   WEBHOOK_URL=https://your-domain.com/webhook/notion
   ```

2. **Запустите webhook сервер:**
   ```bash
   python webhook_server.py
   ```

3. **Создайте webhook подписку:**
   ```bash
   python webhook_manager.py create
   ```

4. **Проверьте статус:**
   ```bash
   python webhook_manager.py list
   ```

**Эндпоинты webhook сервера:**
- `GET /` - проверка работы сервера
- `GET /health` - статус здоровья
- `POST /webhook/notion` - прием уведомлений от Notion
- `POST /test/send` - тестовая отправка сообщения

## 🎯 Использование

### Два режима работы:

1. **🔄 Webhook режим (рекомендуется)** - мгновенные уведомления
2. **⏰ Polling режим** - проверка по расписанию

### Команды для Polling режима

```bash
# Тестирование подключений
python main.py test

# Единичная синхронизация
python main.py once

# Запуск по расписанию (постоянный режим)
python main.py schedule

# Отправка произвольного сообщения
python main.py send "Ваше сообщение"
```

### Команды для Webhook режима

```bash
# Запуск webhook сервера
python webhook_server.py

# Управление webhook подписками
python webhook_manager.py create          # создать webhook
python webhook_manager.py list            # показать все webhooks
python webhook_manager.py delete <id>     # удалить webhook
python webhook_manager.py delete-all      # удалить все webhooks
python webhook_manager.py info <id>       # информация о webhook
python webhook_manager.py config          # показать конфигурацию
```

### Примеры запуска

**Webhook режим:**
```bash
# 1. Запуск сервера
python webhook_server.py

# 2. Создание webhook (в другом терминале)
python webhook_manager.py create

# 3. Тестирование
curl -X POST http://localhost:8000/test/send \
  -H "Content-Type: application/json" \
  -d '{"message": "Тест webhook"}'
```

**Polling режим:**
```bash
# Тестирование настроек
python main.py test

# Запуск постоянной синхронизации
python main.py schedule

# Одноразовая синхронизация
python main.py once
```

## 📊 Структура данных Notion

Скрипт работает с любой базой данных Notion, но для оптимального отображения рекомендуется использовать следующие свойства:

- **Title** (Заголовок) - основное название элемента
- **Status** (Статус) - select свойство со статусами
- **Tags** (Теги) - multi-select свойство с тегами
- **Created time** - автоматическое время создания

### Поддерживаемые статусы с эмодзи:

- `Not Started` → ⏳
- `In Progress` → 🔄  
- `Completed` → ✅
- `Cancelled` → ❌
- `On Hold` → ⏸️
- `Review` → 👀
- `Published` → 🚀
- `Draft` → 📝

## 📱 Формат сообщений в Telegram

Каждый элемент из Notion отправляется как отформатированное сообщение:

```
📝 Название элемента

🔄 Статус: In Progress

🏷️ #тег1 #тег2

📅 25.09.2025 14:30

🔗 Открыть в Notion
```

## 📝 Логирование

Все операции логируются в файл `notion_telegram_sync.log` и выводятся в консоль.

Уровни логирования:
- INFO - обычные операции
- ERROR - ошибки при работе
- WARNING - предупреждения

## ⚠️ Устранение неполадок

### Частые ошибки:

1. **"Отсутствуют обязательные переменные окружения"**
   - Проверьте файл `.env`
   - Убедитесь, что все переменные заполнены

2. **"Ошибка подключения к Notion"**
   - Проверьте токен интеграции
   - Убедитесь, что интеграция добавлена к базе данных
   - Проверьте ID базы данных

3. **"Ошибка подключения к Telegram"**
   - Проверьте токен бота
   - Убедитесь, что бот добавлен в канал как админ
   - Проверьте правильность ID канала

4. **"Сообщения не отправляются"**
   - Проверьте права бота в канале
   - Убедитесь, что канал существует и доступен

### Тестирование по шагам:

```bash
# 1. Проверка переменных окружения
cat .env

# 2. Тестирование подключений
python main.py test

# 3. Пробная синхронизация
python main.py once

# 4. Отправка тестового сообщения
python main.py send "Тест подключения"
```

## 🔧 Дополнительные настройки

### Изменение интервала синхронизации:
В файле `.env` измените `SYNC_INTERVAL_MINUTES=30` на нужное значение в минутах.

### Отключение фильтра новых элементов:
Установите `CHECK_NEW_ITEMS_ONLY=false` для синхронизации всех элементов.

### Настройка форматирования:
Отредактируйте метод `_format_notion_item()` в файле `telegram_client.py`.

## 📞 Поддержка

При возникновении проблем:

1. Проверьте логи в файле `notion_telegram_sync.log`
2. Запустите `python main.py test` для диагностики
3. Убедитесь в правильности всех токенов и ID

## 🚀 Развертывание на сервере

### Webhook режим (рекомендуется)

**1. Использование systemd (Linux):**
```bash
sudo nano /etc/systemd/system/notion-telegram-webhook.service
```

```ini
[Unit]
Description=Notion Telegram Webhook Server
After=network.target

[Service]
Type=simple
User=your_user
WorkingDirectory=/path/to/your/project
ExecStart=/usr/bin/python3 webhook_server.py
Restart=always
Environment=PATH=/usr/bin:/usr/local/bin

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable notion-telegram-webhook
sudo systemctl start notion-telegram-webhook
```

**2. Использование Docker:**
```dockerfile
FROM python:3.9-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .
EXPOSE 8000
CMD ["python", "webhook_server.py"]
```

**3. Nginx прокси (для HTTPS):**
```nginx
server {
    listen 443 ssl;
    server_name your-domain.com;
    
    ssl_certificate /path/to/cert.pem;
    ssl_certificate_key /path/to/key.pem;
    
    location /webhook/notion {
        proxy_pass http://localhost:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

### Polling режим

**1. Использование systemd (Linux):**
```bash
sudo nano /etc/systemd/system/notion-telegram-polling.service
```

```ini
[Unit]
Description=Notion Telegram Polling Sync
After=network.target

[Service]
Type=simple
User=your_user
WorkingDirectory=/path/to/your/project
ExecStart=/usr/bin/python3 main.py schedule
Restart=always

[Install]
WantedBy=multi-user.target
```

**2. Использование screen/tmux:**
```bash
screen -S notion-telegram
python main.py schedule
# Ctrl+A, D для отключения от сессии
``` 