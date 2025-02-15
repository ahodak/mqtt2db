#!/bin/bash

# Создаем пользователя для сервиса
sudo useradd -r -s /bin/false mqtt2db

# Создаем необходимые директории
sudo mkdir -p /etc/mqtt2db
sudo mkdir -p /var/lib/mqtt2db
sudo mkdir -p /var/log

# Копируем файлы
sudo cp mqtt2db.py /usr/local/bin/
sudo cp config.ini /etc/mqtt2db/
sudo chmod +x /usr/local/bin/mqtt2db.py

# Устанавливаем права
sudo chown -R mqtt2db:mqtt2db /var/lib/mqtt2db
sudo chown -R mqtt2db:mqtt2db /etc/mqtt2db
sudo chown mqtt2db:mqtt2db /var/log/mqtt2db.log

# Создаем systemd service файл
cat << EOF | sudo tee /etc/systemd/system/mqtt2db.service
[Unit]
Description=MQTT to SQLite DB Service
After=network.target

[Service]
Type=simple
User=mqtt2db
ExecStart=/usr/local/bin/mqtt2db.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

# Устанавливаем зависимости Python
sudo pip3 install paho-mqtt

# Перезагружаем systemd и запускаем сервис
sudo systemctl daemon-reload
sudo systemctl enable mqtt2db
sudo systemctl start mqtt2db

echo "Установка завершена. Проверьте статус сервиса: sudo systemctl status mqtt2db"
