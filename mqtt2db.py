#!/usr/bin/env python3

#
#  MQTT2DB main file
#  -----------------------------------------------------------------------------------------------------------------------
#  (c) 2025 Ходак Андрей | Andrey Khodak
#  andrey@khodak.ru | https://khodak.ru | tg: @akhodak
#
#  Free to use for any purpose
#

import paho.mqtt.client as mqtt
import sqlite3
import json
import logging
import configparser
import os
from datetime import datetime, timedelta
import signal
import sys
import ast

# Константы
LOG_FILE = '/var/log/mqtt2db.log'

# Настройка логирования
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler()
    ]
)

# Загрузка конфигурации
try:
    config = configparser.ConfigParser()
    if not config.read('config.ini'):
        logging.error("Не удалось прочитать файл конфигурации config.ini")
        sys.exit(1)
except Exception as e:
    logging.error(f"Ошибка при чтении конфигурации: {str(e)}")
    sys.exit(1)

# Проверка обязательных секций
required_sections = ['mqtt', 'database']
for section in required_sections:
    if section not in config:
        logging.error(f"Отсутствует обязательная секция [{section}] в конфигурации")
        sys.exit(1)

# Проверка обязательных параметров в секциях
required_params = {
    'mqtt': ['broker', 'port', 'username', 'password'],
    'database': ['path', 'retention_days']
}

for section, params in required_params.items():
    for param in params:
        if param not in config[section]:
            logging.error(f"Отсутствует обязательный параметр {param} в секции [{section}]")
            sys.exit(1)

# Получение значения из вложенного JSON по пути
def get_nested_value(data, path):
    try:
        for key in path.split('.'):
            if key.isdigit():  # Если ключ - это индекс массива
                key = int(key)
            data = data[key]
        return data
    except (KeyError, TypeError, IndexError):
        logging.debug(f"Не удалось получить значение по пути {path}")
        return None

class MQTT2DB:
    def __init__(self):
        try:
            self.db_path = config['database']['path']
            self.retention_days = int(config['database']['retention_days'])
            
            # Загружаем конфигурацию топиков
            self.topics = {}
            for section in config.sections():
                if section.startswith('table.'):
                    try:
                        topic_config = {
                            'topic': config[section]['topic'],
                            'fields': ast.literal_eval(config[section]['fields'])
                        }
                        self.topics[topic_config['topic']] = topic_config['fields']
                    except KeyError as e:
                        logging.error(f"Отсутствует обязательный параметр в секции [{section}]: {str(e)}")
                        sys.exit(1)
                    except (SyntaxError, ValueError) as e:
                        logging.error(f"Ошибка в формате поля fields в секции [{section}]: {str(e)}")
                        sys.exit(1)
            
            # Создаем директорию для базы данных если её нет
            os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
            
            # Инициализация базы данных
            self.init_database()
            
            # Настройка MQTT клиента
            self.client = mqtt.Client(client_id="mqtt2db", clean_session=True)
            self.client.username_pw_set(
                config['mqtt']['username'],
                config['mqtt']['password']
            )
            
            # Установка обработчиков событий
            self.client.on_connect = self.on_connect
            self.client.on_disconnect = self.on_disconnect
            self.client.on_message = self.on_message
            
            # Настройка автоматического переподключения
            self.client.reconnect_delay_set(min_delay=1, max_delay=60)
            
            # Флаг для отслеживания состояния подключения
            self.connected = False
            
        except Exception as e:
            logging.error(f"Ошибка при инициализации: {str(e)}")
            sys.exit(1)

    def init_database(self):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            # Создаем таблицу для каждого топика
            for section in config.sections():
                if section.startswith('table.'):
                    table_name = section[6:]  # Убираем префикс 'table.'
                    fields = ast.literal_eval(config[section]['fields'])
                    
                    # Создаем SQL-запрос для создания таблицы
                    columns = ['timestamp DATETIME DEFAULT CURRENT_TIMESTAMP']
                    for json_path, db_field in fields.items():
                        columns.append(f'{db_field} REAL')
                    
                    create_table_sql = f'''
                        CREATE TABLE IF NOT EXISTS {table_name} (
                            {', '.join(columns)}
                        )
                    '''
                    
                    cursor.execute(create_table_sql)
                    
                    # Создаем индекс по времени для быстрой очистки старых данных
                    cursor.execute(f'''
                        CREATE INDEX IF NOT EXISTS idx_{table_name}_timestamp 
                        ON {table_name}(timestamp)
                    ''')
            
            conn.commit()
            logging.info("База данных инициализирована")

    def cleanup_old_data(self):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cutoff_date = datetime.now() - timedelta(days=self.retention_days)
            
            # Очищаем старые данные во всех таблицах топиков
            for section in config.sections():
                if section.startswith('table.'):
                    table_name = section[6:]  # Убираем префикс 'table.'
                    cursor.execute(
                        f'DELETE FROM {table_name} WHERE timestamp < ?',
                        (cutoff_date,)
                    )
                    logging.info(f"Удаление старых данных из таблицы {table_name}: удалено {cursor.rowcount} строк")
            
            conn.commit()

    def on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            self.connected = True
            logging.info("Подключено к MQTT брокеру")
            # Подписываемся на все топики
            for topic in self.topics.keys():
                client.subscribe(topic)
                logging.info(f"Подписка на топик: {topic}")
        else:
            self.connected = False
            logging.error(f"Ошибка подключения к MQTT брокеру, код: {rc}")

    def on_disconnect(self, client, userdata, rc):
        self.connected = False
        if rc != 0:
            logging.warning(f"Неожиданное отключение от MQTT брокера. Код: {rc}")
        else:
            logging.info("Отключено от MQTT брокера")

    def on_message(self, client, userdata, msg):
        try:
            topic = msg.topic
            if topic not in self.topics:
                return
            
            data = json.loads(msg.payload)
            field_mappings = self.topics[topic]
            
            # Находим имя таблицы по топику
            table_name = None
            for section in config.sections():
                if section.startswith('table.') and config[section]['topic'] == topic:
                    table_name = section[6:]  # Убираем префикс 'table.'
                    break
            
            if not table_name:
                logging.error(f"Не найдена таблица для топика {topic}")
                return
            
            # Создаем словарь значений для записи
            values = {}
            for json_path, db_field in field_mappings.items():
                value = get_nested_value(data, json_path)
                values[db_field] = value if value is not None else None
            
            # Сохраняем в базу данных
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                columns = list(values.keys())
                placeholders = ','.join(['?' for _ in values])
                query = f'''
                    INSERT INTO {table_name} 
                    ({','.join(columns)}) 
                    VALUES ({placeholders})
                '''
                cursor.execute(query, list(values.values()))
                conn.commit()
                logging.debug(f"Сохранены значения для топика {topic} в таблицу {table_name}: {values}")
            
        except json.JSONDecodeError:
            logging.error(f"Ошибка декодирования JSON из топика {topic}")
        except Exception as e:
            logging.error(f"Ошибка обработки сообщения из топика {topic}: {str(e)}")

    def connect_mqtt(self):
        try:
            # Установка соединения с брокером
            self.client.connect(
                config['mqtt']['broker'],
                int(config['mqtt']['port']),
                keepalive=60
            )
            return True
        except Exception as e:
            logging.error(f"Ошибка подключения к MQTT брокеру: {str(e)}")
            return False

    def run(self):
        # Обработка сигналов завершения
        signal.signal(signal.SIGTERM, self.signal_handler)
        signal.signal(signal.SIGINT, self.signal_handler)
        
        try:
            # Попытка подключения к брокеру
            if not self.connect_mqtt():
                logging.error("Не удалось подключиться к MQTT брокеру")
                sys.exit(1)
            
            # Запускаем очистку старых данных раз в сутки
            self.cleanup_old_data()
            
            # Запуск цикла обработки сообщений
            self.client.loop_start()
            
            # Основной цикл программы
            while True:
                if not self.connected:
                    logging.warning("Соединение потеряно, ожидание восстановления...")
                signal.pause()
                
        except Exception as e:
            logging.error(f"Ошибка выполнения: {str(e)}")
            self.client.loop_stop()
            sys.exit(1)

    def signal_handler(self, signum, frame):
        logging.info("Получен сигнал завершения, останавливаем сервис...")
        self.client.loop_stop()
        self.client.disconnect()
        sys.exit(0)

if __name__ == "__main__":
    mqtt2db = MQTT2DB()
    mqtt2db.run()
