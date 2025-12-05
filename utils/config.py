import os
base_path = os.getcwd() +"/"

pika_name = 'nano'
vicki_app = 'http://192.168.1.140:8085/tsv/flashapi'
archive = False
Queue = 'cvRequest'
local_queue = 'cvCPP'
camera_resolution = (640, 480) # for arducam
resize_images = (640,480)
cameras_to_flip = []
minutes_to_end_transcation = 300
warning_message_time = 180
log_folder  = 'logs'
log_file = 'Camera-Preview.log'
message_timeout = 3600
save_frame = 2 #Save every alternate frame
pipeline_status_interval = 10800
version_file_path = 'version.txt'
delete_logs_days = 30
no_camera_alert_time = 'last_alert.txt'