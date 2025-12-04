def get_version_from_file(file_path):
    try:
        with open(file_path, "r") as file:
            version = file.readline().strip()
            return version
    
    except FileNotFoundError:
        print(f"File not found: {file_path}")
        return None
    except Exception as e:
        print(f"An error occurred: {e}")
        return None

def get_time_from_file(file_path):
    try:
        with open(file_path, "r") as file:
            last_alert_time = file.readline().strip()
            return float(last_alert_time)
    
    except FileNotFoundError:
        print(f"File not found: {file_path}")
        return 0
    except Exception as e:
        print(f"An error occurred: {e}")
        return 0

def update_alert_time(file_path, alert_time):
    with open(file_path, "w") as f:
        f.write(str(alert_time))