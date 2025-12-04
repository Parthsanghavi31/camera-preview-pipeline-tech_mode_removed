import os
from datetime import datetime, timedelta

def is_uptime_less_than_5_minutes():
    try:
        with open("/proc/uptime", "r") as f:
            uptime_seconds = float(f.readline().split()[0])
        return uptime_seconds < 300
    except Exception as e:
        return False

def delete_old_log_files(log_dir, current_date, days_old):
    if not os.path.exists(log_dir):
        return
    
    threshold_date = current_date - timedelta(days=days_old)
    for log_file in os.listdir(log_dir):
        log_path = os.path.join(log_dir, log_file)
        
        if os.path.isfile(log_path):
            try:
                file_date = datetime.strptime(log_file.split('.log')[0], "%Y-%m-%d")
                if file_date < threshold_date:
                    os.remove(log_path)
            except ValueError:
                print(f"Skipping non-log file: {log_file}")
