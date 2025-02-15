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

# Загрузка конфигурации
config = configparser.ConfigParser()
config.read('config.ini')

# Настройка логирования
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(config['logging']['log_file']),
        logging.StreamHandler()
    ]
)

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
        self.db_path = config['database']['path']
        self.retention_days = int(config['database']['retention_days'])
        
        # Загружаем конфигурацию топиков
        self.topics = {}
        for section in config.sections():
            if section.startswith('topic.'):
                topic_config = {
                    'topic': config[section]['topic'],
                    'fields': ast.literal_eval(config[section]['fields'])
                }
                self.topics[topic_config['topic']] = topic_config['fields']
        
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

    def init_database(self):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            # Собираем все уникальные поля из всех топиков
            all_fields = set()
            for fields in self.topics.values():
                all_fields.update(fields.values())
            
            # Создаем таблицу для данных
            columns = ', '.join([f'{field} REAL' for field in all_fields])
            cursor.execute(f'''
                CREATE TABLE IF NOT EXISTS sensor_data (
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    topic TEXT,
                    {columns}
                )
            ''')
            
            # Создаем индекс по времени для быстрой очистки старых данных
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_timestamp 
                ON sensor_data(timestamp)
            ''')
            conn.commit()
            logging.info("База данных инициализирована")

    def cleanup_old_data(self):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cutoff_date = datetime.now() - timedelta(days=self.retention_days)
            cursor.execute(
                'DELETE FROM sensor_data WHERE timestamp < ?',
                (cutoff_date,)
            )
            conn.commit()
            logging.info(f"Удаление старых данных: удалено {cursor.rowcount} строк")

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
            
            # Создаем словарь значений для записи
            values = {'topic': topic}
            for json_path, db_field in field_mappings.items():
                value = get_nested_value(data, json_path)
                values[db_field] = value if value is not None else None
            
            # Сохраняем в базу данных
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                columns = ['topic'] + list(values.keys())[1:]
                placeholders = ','.join(['?' for _ in values])
                query = f'''
                    INSERT INTO sensor_data 
                    ({','.join(columns)}) 
                    VALUES ({placeholders})
                '''
                cursor.execute(query, list(values.values()))
                conn.commit()
                logging.debug(f"Сохранены значения для топика {topic}: {values}")
            
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
