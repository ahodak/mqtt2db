# MQTT2DB

MQTT2DB - это Python-сервис для сохранения данных из MQTT-топиков в базу данных SQLite. Идеально подходит для долгосрочного хранения данных с датчиков, устройств умного дома и других IoT-устройств.

## Возможности

- Подписка на множество MQTT-топиков
- Гибкая настройка маппинга данных из JSON в базу данных
- Автоматическая очистка устаревших данных
- Поддержка вложенных JSON-структур
- Настраиваемый период хранения данных
- Логирование всех операций
- Отдельные таблицы для каждого топика

## Установка

1. Клонируйте репозиторий:

```bash
git clone https://github.com/ahodak/mqtt2db.git
cd mqtt2db
```

1. Создайте необходимые директории:

```bash
sudo mkdir /etc/mqtt2db
sudo mkdir /var/lib/mqtt2db
sudo mkdir /var/log/mqtt2db
```

1. Скопируйте файлы конфигурации:

```bash
sudo cp config.ini /etc/mqtt2db/
sudo cp mqtt2db.py /usr/local/bin/
```

1. Установите зависимости:

```bash
pip3 install paho-mqtt
```

## Конфигурация

Файл конфигурации `/etc/mqtt2db/config.ini` содержит все необходимые настройки:

```ini
[mqtt]
broker = your.mqtt.broker.url
port = 1883
username = your_username
password = your_password

[database]
path = /var/lib/mqtt2db/data.sqlite
retention_days = 365

[table.example]
topic = your/mqtt/topic
fields = {
    "json.path": "database_field"
}
```

### Настройка топиков

Каждый топик настраивается в отдельной секции `[table.name]`:

- `topic` - MQTT-топик для подписки
- `fields` - словарь маппинга полей из JSON в базу данных
  - ключ - путь к значению в JSON (поддерживается вложенность через точку)
  - значение - название поля в базе данных

Название секции `[table.name]` определяет имя таблицы в базе данных (без префикса 'table.').

## Использование

Запуск сервиса:

```bash
python3 /usr/local/bin/mqtt2db.py
```

Для автоматического запуска можно использовать systemd-сервис.

## Структура базы данных

Для каждого топика создается отдельная таблица в базе данных SQLite. Название таблицы соответствует названию секции в конфигурации без префикса 'table.'.

Структура каждой таблицы:
- `timestamp` - время получения данных (DATETIME)
- Поля, указанные в конфигурации топика (REAL)

Например, для конфигурации:
```ini
[table.opentherm]
topic = opentherm/status
fields = {
    "master.heating.currentTemp": "heating_temp",
    "master.heating.indoorTemp": "indoor_temp",
    "master.dhw.currentTemp": "dhw_temp"
}
```

Будет создана таблица `opentherm` со следующими полями:
- timestamp (DATETIME)
- heating_temp (REAL)
- indoor_temp (REAL)
- dhw_temp (REAL)

## Логирование

Логи сохраняются в:
- `/var/log/mqtt2db.log`
- Также выводятся в стандартный вывод

## Лицензия

Свободное использование для любых целей.

## Автор

Андрей Ходак

- Web: <https://khodak.ru>
- Telegram: @akhodak

## Вклад в проект

Если вы хотите внести свой вклад в проект:

1. Создайте форк репозитория
2. Внесите изменения
3. Отправьте pull request
