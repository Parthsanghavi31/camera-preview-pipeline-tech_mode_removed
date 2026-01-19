sudo apt-get install curl -y
echo "Setting timezone..."
timezone=$(curl -s http://ip-api.com/line/?fields=timezone)
sudo timedatectl set-timezone "$timezone"

echo "Configuring passwordless sudo for reboot..."
user=$(whoami)
sudo sed -i "/^${user} ALL=(ALL) NOPASSWD: \/sbin\/reboot$/d" /etc/sudoers
echo "${user} ALL=(ALL) NOPASSWD: /sbin/reboot" | sudo tee -a /etc/sudoers

echo "Setting up cron job for daily reboot at 2 AM in root's crontab..."
temp_cron=$(mktemp)
sudo crontab -l > "$temp_cron"
cron_job="0 2 * * * /sbin/reboot"
cleanup_job="0 1 * * 0 rm -rf /home/parth/camera-preview-pipeline-tech_mode_removed/post_archive/* /home/parth/camera-preview-pipeline-tech_mode_removed/archive/*"

if ! grep -Fxq "$cron_job" "$cleanup_job" "$temp_cron"; then
    echo "$cron_job" >> "$temp_cron"
    echo "$cleanup_job" >> "$temp_cron"
fi
sudo crontab "$temp_cron"
rm "$temp_cron"
sudo systemctl restart cron
echo "Configuration complete."

