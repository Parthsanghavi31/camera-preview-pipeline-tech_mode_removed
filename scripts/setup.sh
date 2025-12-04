sudo apt-get update
sudo apt-get install -y python3-dev python3-pip build-essential libjpeg-dev zlib1g-dev

pip3 install --user --upgrade pip setuptools wheel
pip3 install --user pika

get_device_type() {
    if grep -q "NVIDIA Jetson Nano" /proc/device-tree/model; then
        echo "Jetson Nano"
    elif grep -q "Raspberry Pi" /proc/device-tree/model; then
        echo "Raspberry Pi"
    else
        echo "Unknown Device"
    fi
}

device_type=$(get_device_type)
echo "Detected device: $device_type"
pip3 install --user --upgrade pip setuptools wheel

if [ "$device_type" == "Jetson Nano" ]; then
    echo "Installing packages for Jetson Nano..."
    pip3 install --user numpy==1.17.4
    pip3 install --user moviepy
    pip3 install --user pillow
    pip3 install --user imageio_ffmpeg==0.3
else
    echo "Installing moviepy for other devices..."
    pip3 install --user moviepy
fi

is_rabbitmq_installed() {
    dpkg -l | grep -q rabbitmq-server
}
if is_rabbitmq_installed; then
    echo "RabbitMQ is already installed."
    if sudo rabbitmqctl list_users | grep -q "^nano"; then
        echo "User 'nano' already exists in RabbitMQ."
    else
        echo "Creating 'nano' user in RabbitMQ..."
        sudo rabbitmqctl add_user nano nano
        sudo rabbitmqctl set_permissions -p / nano ".*" ".*" ".*"
    fi
else
    echo "Installing RabbitMQ..."
    sudo apt update -y
    sudo apt install rabbitmq-server -y
    sudo rabbitmq-plugins enable rabbitmq_management
    sudo service rabbitmq-server start

    echo "Creating 'nano' user in RabbitMQ..."
    sudo rabbitmqctl add_user nano nano
    sudo rabbitmqctl set_permissions -p / nano ".*" ".*" ".*"
    sudo service rabbitmq-server restart
fi

if [ -f /etc/systemd/system/camera-preview.service ]; then
    echo "Stopping camera-preview.service..."
    sudo systemctl stop camera-preview.service
    sudo systemctl disable camera-preview.service
    sudo rm -f /etc/systemd/system/camera-preview.service
    sudo systemctl daemon-reload
else
    echo "camera-preview.service is not running."
fi

if [ -f /etc/systemd/system/upload.service ]; then
    echo "Stopping upload.service..."
    sudo systemctl stop upload.service
    sudo systemctl disable upload.service
    sudo rm -f /etc/systemd/system/upload.service
    sudo systemctl daemon-reload
else
    echo "upload.service is not running."
fi

### Camera Preview Pipeline Service###
user=${SUDO_USER:-$(whoami)}
current_dir=$(pwd)
current_dir=${current_dir%/scripts}
original_service="[Unit]
Description=camera-preview.service
After=network.target rabbitmq-server.service

[Service]
User=${user}
Type=idle
WorkingDirectory=${current_dir}
ExecStart=/usr/bin/python3 -u main.py
StandardOutput=inherit
StandardError=inherit
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target"

echo "$original_service" > camera-preview.service
sudo mv camera-preview.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable camera-preview.service
sudo systemctl start camera-preview.service

### Camera Preview Upload Service###
user=${SUDO_USER:-$(whoami)}
current_dir=$(pwd)
current_dir=${current_dir%/scripts}
upload_service="[Unit]
Description=upload.service
After=network.target

[Service]
User=${user}
Type=idle
WorkingDirectory=${current_dir}
ExecStart=/usr/bin/python3 -u upload_module.py
StandardOutput=inherit
StandardError=inherit
Restart=always
RestartSec=3600

[Install]
WantedBy=multi-user.target"

echo "$upload_service" > upload.service
sudo mv upload.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable upload.service
sudo systemctl start upload.service
