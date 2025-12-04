import logging
import requests
import os
import traceback
import sys
from datetime import datetime
import shutil
import time
import moviepy.video.io.ImageSequenceClip
from utils import config
from utils import login
from utils.send_alert import send_alert
import threading

class VideoArchiver:
    def __init__(self):
        self.logger = self.log_setup()
        self.current_hour = datetime.now().hour
        self.archive_path = 'archive'
        self.post_archive_path = 'post_archive'
        os.makedirs('temp', exist_ok= True)
        
        if not (0 <= self.current_hour < 5):
            self.logger.info("Script runs only between 12 AM and 5 AM")
            sys.exit()

    def log_setup(self):
        logging.getLogger("pika").setLevel(logging.WARNING)
        logging.getLogger('requests').setLevel(logging.WARNING)
        logging.getLogger("tensorflow").setLevel(logging.ERROR)

        log_folder = os.path.join(os.getcwd(), config.log_folder)
        os.makedirs(log_folder, exist_ok=True)
        log_path = os.path.join(log_folder, 'Upload-Module.log')

        if not os.path.exists(log_path):
            open(log_path, 'w').close()

        logging.basicConfig(filename=log_path, level=logging.DEBUG, format="%(asctime)-8s %(levelname)-8s %(message)s")
        logging.disable(logging.DEBUG)
        logger = logging.getLogger()
        logger.info("")
        sys.stderr.write = logger.error
        return logger

    def make_archive(self, source, destination, format='zip'):
        base, name = os.path.split(destination)
        archive_from = os.path.dirname(source)
        archive_to = os.path.basename(source.strip(os.sep))
        shutil.make_archive(name, format, archive_from, archive_to)
        shutil.move(f'{name}.{format}', destination)
        shutil.rmtree(source)

    def create_video(self, source, destination, trans_id):
        images_path = os.path.join(source, 'Frames')
        video_path = os.path.join(source, 'media.mp4')

        if os.path.exists(images_path):
            self.logger.info("Creating Video of {}".format(trans_id))
            images = [img for img in os.listdir(images_path) if img.endswith(".jpg")]
            images.sort(key=lambda x: int(x.split('.')[0]))
            frames = [os.path.join(images_path, image) for image in images]
            clip = moviepy.video.io.ImageSequenceClip.ImageSequenceClip(frames, fps=10)
            clip.write_videofile(video_path, verbose=False, logger=None)
            os.system('rm -r {}'.format(images_path))
        
        if os.path.exists(video_path):
            self.logger.info("Creating Archive of {}".format(trans_id))
            os.makedirs(os.path.join(config.base_path, 'post_archive', trans_id), exist_ok=True)
            self.make_archive(source, destination)

    def upload_video(self, trans_id, post_transid):
        with open(f'post_archive/{trans_id}.zip', 'rb') as fileobj:
            self.logger.info("Uploading Archive... {}".format(trans_id))

            base_url, machine_id, machine_token, machine_api_key = login.get_custom_machine_settings(config.vicki_app, self.logger)
            access_token = login.get_current_access_token(base_url, machine_id, machine_token, machine_api_key, self.logger)
            headers = {"Authorization": "Bearer {}".format(access_token)}
            try:
                response_media = requests.post(f"{base_url}/loyalty/upload-media/cv?media_event_type=COMPUTER_VISION&invoice_id={post_transid}", 
                                                files={'file': fileobj}, headers=headers)

                if response_media.status_code == 200:
                    status = f' Media Uploaded Successfully (Transaction: {post_transid}) File-size: {file_size_mb:.2f} MB'
                    self.logger.info("Uploading media - Success")
                    os.system("rm -r post_archive/{}".format(trans_id))
                    os.system("rm -r post_archive/{}.zip".format(trans_id))
                    self.logger.info("Cleaned Transaction")
                    threading.Thread(target=send_alert, args=(self.logger,config.vicki_app,status,False)).start()
                else:
                    os.system("mv post_archive/{}.zip temp/".format(trans_id))
                    self.logger.info("Response: {}".format(response_media))
                    self.logger.info("Uploading media - FAILED")
                    self.logger.info("Archiving Transaction / For batch processing")
                    self.logger.info("Finished Current Transaction")
            except Exception as e:
                self.logger.info("Uploading media - Failed")
                self.logger.info(traceback.format_exc())

    def is_folder_created_recently(self, folder_path):
        current_time = time.time()
        folder_creation_time = os.path.getctime(folder_path)
        return (current_time - folder_creation_time) < 1800

    def process_archives(self):
        if os.path.exists(self.archive_path):
            for trans_id in os.listdir(self.archive_path):
                if not self.is_folder_created_recently(os.path.join(self.archive_path, trans_id)):
                    if 'technician' in trans_id:
                        self.logger.info(f'deleting the transaction {trans_id}')
                        shutil.rmtree(os.path.join(self.archive_path,trans_id))
                    else:
                        try:  
                            self.create_video(os.path.join(self.archive_path, trans_id), f'post_archive/{trans_id}.zip', trans_id)
                        except:
                            pass
                else:
                    self.logger.info("Folder created within the last 30 mins")

        if os.path.exists(self.post_archive_path):
            for transid in os.listdir(self.post_archive_path):
                if '.zip' in transid:
                    trans_id = transid.split('.zip')[0]
                    post_transid = trans_id.split("____")[0] if "____" in trans_id else trans_id
                    self.upload_video(trans_id=trans_id, post_transid=post_transid)
        else:
            self.logger.info("No Failed Transaction found")

    def main(self):
        self.process_archives()

if __name__ == "__main__":
    archiver = VideoArchiver()
    archiver.main()
