import multiprocessing
import threading
import cv2
import numpy as np
import os
import logging
import sys
from utils.rabbitmq import message_processing
from utils.sendData import upload_video
from utils import config
import shutil
import re
import uuid
from utils.device_utils import is_uptime_less_than_5_minutes, delete_old_log_files
from utils.utils import get_version_from_file, get_time_from_file, update_alert_time
from utils.send_alert import send_alert
from datetime import datetime, timedelta
import time


class CameraPreview:
    def __init__(self):
        current_date_time = datetime.now()
        if current_date_time.hour >= 2:
            log_file = str(datetime.now().date()) + '.log'
        else:
            log_file = str(datetime.now().date() - timedelta(days=1)) + '.log'
        delete_old_log_files(config.log_folder, current_date_time, config.delete_logs_days)
        
        self.log_setup(log_file)
        self.working_camera_indices = []
        self.camera_indices = self.get_camera_indices()
        self.last_alert_time = get_time_from_file(config.no_camera_alert_time)
        self.caps = self.init_cameras(self.camera_indices)
        
        # self.fgbg = cv2.createBackgroundSubtractorMOG2()
        self.frame_number = 0
        self.recv = None
        self.transid = None
        self.door_opened = False
        self.frames_path = None
        self.frames_to_save = 0
        self.frames_to_save_after_door_closed = 15
        self.manager = multiprocessing.Manager()
        self.lock = self.manager.Lock()
        self.upload_process = None
        self.is_customer_trans = None
        self.technician_trans_id = None
        self.rabbitmq_process = None
        
        if is_uptime_less_than_5_minutes():
            version = get_version_from_file(config.version_file_path)
            if version:
                version_status = f'Camera Preview Pipeline version: {version}'
                threading.Thread(target=send_alert, args=(self.logger, config.vicki_app, version_status, False)).start()
            cameras_message = f'{len(self.camera_indices)} camera{"s" if len(self.camera_indices) != 1 else ""} connected and {len(self.caps)} camera{"s" if len(self.caps) != 1 else ""} working'
            threading.Thread(target=send_alert, args=(self.logger, config.vicki_app, cameras_message, False)).start()
        
        if len(self.caps) ==0:
            current_time = time.time()
            if current_time - self.last_alert_time >= config.message_timeout:
                no_camera_alert = "No Camera Connnected"
                threading.Thread(target=send_alert, args=(self.logger, config.vicki_app, no_camera_alert)).start()
                update_alert_time(config.no_camera_alert_time, current_time)
                time.sleep(5)
            self.cleanup()

        self.message_queue = multiprocessing.Queue()
        self.rabbitmq_process = multiprocessing.Process(target=message_processing, args = (self.logger, config.pika_name, config.Queue, self.message_queue, config.vicki_app, config.minutes_to_end_transcation, config.warning_message_time, config.message_timeout, config.pipeline_status_interval))
        self.rabbitmq_process.start()

    def get_camera_indices(self):
        dev_list = os.listdir('/dev')
        video_devices = [entry for entry in dev_list if re.match(r'video\d+', entry)]
        indices = [int(device[5:]) for device in video_devices]
        return sorted(indices)
        
    def log_setup(self, file_name):
        logging.getLogger("pika").setLevel(logging.WARNING)
        logging.getLogger('requests').setLevel(logging.WARNING)
        logging.getLogger("tensorflow").setLevel(logging.ERROR)

        log_folder = os.path.join(os.getcwd(), config.log_folder)
        os.makedirs(log_folder, exist_ok=True)
        log_path = os.path.join(log_folder, file_name)
        

        if not os.path.exists(log_path):
            open(log_path, 'w').close()

        logging.basicConfig(filename=log_path, level=logging.DEBUG, format="%(asctime)-8s %(levelname)-8s %(message)s")
        logging.disable(logging.DEBUG)
        self.logger = logging.getLogger()
        self.logger.info("")
        sys.stderr.write = self.logger.error

    def check_camera(self, sensor_id):
        cap=cv2.VideoCapture('/dev/video'+str(sensor_id))
        if cap.isOpened():
            ret, frame = cap.read()
            if ret:
                return True
            else:
                return False
        else:
            return False
            
    def init_camera(self, sensor_id):
        if not os.path.exists(f'/dev/video{sensor_id}'):
            return None, None

        if not self.check_camera(sensor_id):
            return None, None
        csi_pipeline = (
            f"nvarguscamerasrc sensor_id={sensor_id} ! video/x-raw(memory:NVMM), "
            f"width=(int){config.camera_resolution[0]}, height=(int){config.camera_resolution[1]}, format=(string)NV12, framerate=(fraction)21/1 ! "
            "nvvidconv flip-method=2 ! video/x-raw, "
            f"width=(int){config.camera_resolution[0]}, height=(int){config.camera_resolution[1]}, format=(string)BGRx ! "
            "videoconvert ! video/x-raw, format=(string)BGR ! appsink"
        )
        #cap = cv2.VideoCapture(csi_pipeline, cv2.CAP_GSTREAMER)
        #if cap.isOpened():
            #return cap

        flip = 1 if sensor_id in config.cameras_to_flip else 0

        usb_pipeline = (
            f'v4l2src device=/dev/video{sensor_id} ! '
            f'image/jpeg, width={config.camera_resolution[0]}, height={config.camera_resolution[1]}, framerate=80/1 ! '
            'jpegdec ! '
            'videoconvert ! '
            'appsink'
        )
        cap = cv2.VideoCapture(usb_pipeline, cv2.CAP_GSTREAMER)
        # cap = cv2.VideoCapture(f'/dev/video{sensor_id}')
        if cap.isOpened():
            if sensor_id not in self.working_camera_indices:
                self.working_camera_indices.append(sensor_id)
            return cap, flip
        
        else:
            return None, None
        
    def re_initialize_camera(self, sensor_id, camera_index): #[0,2], [0,1]
        self.caps[camera_index][0].release()
        cap, flip = self.init_camera(sensor_id)
        if cap is not None:
            return cap, flip
        else:
            return None, None
        
    def init_cameras(self, sensor_ids):
        caps = []
        for sensor_id in sensor_ids:
            cap, flip = self.init_camera(sensor_id)
            if cap is not None:
                caps.append([cap, flip])
        return caps

    def process_frames(self):
        print(self.caps)
        termination_flags = [False]*len(self.caps)
        disconnected_cameras = []

        
        while True:
            frames = []

            if not self.message_queue.empty():
                self.recv = self.message_queue.get()
                if self.recv:
                    self.handle_message() 
                
            for idx, cap in enumerate(self.caps):
                if cap[0] is not None:
                    ret, frame = cap[0].read()
                    if ret:
                        if cap[1]:
                            frame = cv2.flip(frame, 0)
                        frames.append(cv2.resize(frame, config.resize_images))
                    else:
                        termination_flags[idx] = True
                        frames.append(np.full((config.resize_images[1], config.resize_images[0], 3), (0, 255, 0), dtype=np.uint8))
                else:
                    frames.append(np.full((config.resize_images[1], config.resize_images[0], 3), (0, 255, 0), dtype=np.uint8))

            if not self.door_opened:
                if any(termination_flags):
                    for i in range(len(termination_flags)):
                        if termination_flags[i] == True:
                            cap, flip = self.re_initialize_camera(self.working_camera_indices[i], i)
                            if cap is not None:
                                self.caps[i] = (cap, flip)
                                self.logger.info(f"Reinitialized camera {i}")
                            else:
                                self.logger.info(f"Reinitialized failed for camera {i}")
                                disconnected_cameras.append(i)

                    termination_flags = [False]*len(self.caps)
                
                if disconnected_cameras:                        
                    for i in reversed(disconnected_cameras):
                        self.caps.pop(i)
                        self.working_camera_indices.pop(i)

                    disconnected_cameras.clear()
                    termination_flags = [False]*len(self.caps)

                    if not self.caps:
                        self.logger.info('No camera connected Stopping the pipeline')
                        self.cleanup()
                    
            if self.door_opened:
                if all(termination_flags):
                    self.logger.error("Failed to capture frame or end of video")
                    for i in range(len(termination_flags)):
                        cap, flip = self.re_initialize_camera(self.working_camera_indices[i], i)
                        if cap is not None:
                            self.caps[i] = (cap, flip)
                            self.logger.info(f"Reinitialized camera {i}")
                        else:
                            self.logger.info(f"Failed to Reinitialize camera {i}")
                            self.caps[i] = (None, None)
                            disconnected_cameras.append(i)
                            
                    termination_flags = [False]*len(self.caps)

                self.save_frames(frames)
                #self.frame_number += 1
            else:
                pass
                #self.detect_person(frames[0])
            self.frame_number += 1
        self.cleanup()

    def handle_door_opened(self):
        self.transid = self.recv["parm1"].split(":")[0]
        self.is_customer_trans = self.recv["parm1"].split(":")[1]
        self.logger.info('\n')
        self.logger.info("    RECV: DoorOpened")
        self.logger.info("    RECV: {}".format(self.recv['parm1']))
        if self.is_customer_trans=='False':
            self.transid = self.transid + '_technician'
        self.door_opened = True
        self.transid_path = os.path.join(config.base_path, 'archive', self.transid)
        self.frames_path = os.path.join(self.transid_path, 'Frames')
        
        if os.path.exists(self.transid_path):
            self.transid = self.transid + "____" + str(uuid.uuid4())
            self.transid_path = os.path.join(config.base_path, 'archive', self.transid)
            self.frames_path = os.path.join(self.transid_path, 'Frames')
            # shutil.rmtree(self.transid_path)
        
        os.makedirs(self.frames_path, exist_ok=True)

    def handle_door_locked(self):
        self.logger.info("    RECV: {}".format(self.recv["cmd"]))        
        if self.transid:
            self.door_opened = False
        else:
            self.logger.info("DoorOpened Message wasn't received")

    def handle_technician(self):
        self.logger.info("    RECV: {}".format(self.recv["cmd"]))
        if self.is_customer_trans == 'False':
            self.technician_trans_id = self.recv["parm1"]
            self.logger.info(f"    TECH-TRANSID: {self.technician_trans_id}")
            self.door_opened = False
            
            if self.transid:
                self.start_upload_process(self.technician_trans_id)
                self.transid = None
                self.is_customer_trans = None
            else:
                self.logger.info("DoorOpened Message wasn't received")
    
    def handle_order_settled(self):
        post_transid = self.recv["parm1"].split(":")[1]        
        self.logger.info("    RECV: OrderSettled")
        self.logger.info(f"    POST-TRANSID: {post_transid}")
        self.door_opened = False        
        if self.transid:
            self.start_upload_process(post_transid)
            self.transid = None
            self.is_customer_trans = None
        elif self.technician_trans_id:
            self.logger.info("Discarding the OrderSettled Message for Technician Transaction")
            self.technician_trans_id = None
        else:
            self.logger.info("DoorOpened Message wasn't received")

    def start_upload_process(self, post_transid):
        self.upload_process = multiprocessing.Process(
            target=self.generate_and_upload_video, 
            args=(self.logger, self.transid, post_transid, 
                self.frames_path, 
                os.path.join(self.transid_path, 'media.mp4'), 
                self.is_customer_trans)
        )
        self.upload_process.start()

    def handle_message(self):
        if self.recv['cmd'] == 'DoorOpened':
            self.handle_door_opened()

        elif self.recv['cmd'] == 'Technician':
            self.handle_technician()
        
        elif self.recv['cmd'] == 'DoorLocked':
            self.handle_door_locked()

        elif self.recv['cmd'] == 'OrderSettled':
            self.handle_order_settled()
            
        elif self.recv['cmd'] == 'Stop':
            self.logger.info('Error in RabbitMQ Exiting the Pipeline')
            self.cleanup()
            

    def cleanup(self):
        for cap in self.caps:
            cap[0].release()
        if self.rabbitmq_process and self.rabbitmq_process.is_alive():
            self.rabbitmq_process.terminate()

        if self.upload_process and self.upload_process.is_alive():
            self.upload_process.join()
        os._exit(1)

    def generate_and_upload_video(self, logger, transid, post_transid, images_path, video_path, technician_trans):
        with self.lock:
            upload_video(logger, transid, post_transid, images_path, video_path, technician_trans)

    def save_frames(self, frames):
        if self.frame_number % config.save_frame ==0:
            num_frames = len(frames)
            if num_frames > 2:
                if num_frames % 2 == 0:
                    rows = num_frames // 2
                    cols = 2
                else:
                    rows = (num_frames // 2) + 1
                    cols = 2
                canvas_height = rows * frames[0].shape[0]
                canvas_width = cols * frames[0].shape[1]
                canvas = np.zeros((canvas_height, canvas_width, 3), dtype=np.uint8)
                for i, frame in enumerate(frames):
                    r = i // cols
                    c = i % cols
                    if num_frames % 2 != 0 and i == num_frames - 1:
                        pad_left = (canvas_width - frame.shape[1]) // 2
                        canvas[r * frame.shape[0]:(r + 1) * frame.shape[0], pad_left:pad_left + frame.shape[1]] = frame
                    else:
                        canvas[r * frame.shape[0]:(r + 1) * frame.shape[0], c * frame.shape[1]:(c + 1) * frame.shape[1]] = frame
            else:
                canvas=np.hstack(frames)
            
            if not self.is_black_frame(canvas):
                img_path = os.path.join(self.frames_path, f"{self.frame_number}.jpg")
                cv2.imwrite(img_path, canvas)

    def detect_person(self, frame):
        fgmask = self.fgbg.apply(frame)
        contours, _ = cv2.findContours(fgmask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        person_detected = False

        for contour in contours:
            if cv2.contourArea(contour) > 1000:  
                person_detected = True
                break

        if person_detected:
            print("Person Detected")
            
    def is_black_frame(self, frame, threshold=80):
        gray_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        total_pixels = gray_frame.size
        black_pixels = np.sum(gray_frame < 10)
        black_percentage = (black_pixels / total_pixels) * 100
        
        return black_percentage >= threshold

if __name__ == "__main__":
    camera_preview = CameraPreview()
    camera_preview.process_frames()
