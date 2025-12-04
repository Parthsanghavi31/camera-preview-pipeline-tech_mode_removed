import threading
import time
import requests
import os
import cv2
from utils import config
import shutil
from utils import login
import sys
import traceback
import moviepy.video.io.ImageSequenceClip
from utils.send_alert import send_alert

os.makedirs(os.path.join(config.base_path, 'post_archive'), exist_ok= True)
os.makedirs(os.path.join(config.base_path, 'temp'), exist_ok= True)
os.makedirs(os.path.join(config.base_path, 'temp_archive'), exist_ok= True)


def make_archive(source, destination, format='zip', temp_archive_path ='temp_archive'):
    base, name = os.path.split(destination)
    name = os.path.splitext(name)[0]
    new_source = os.path.join(temp_archive_path, name)
    shutil.move(source, new_source)
    archive_from = temp_archive_path
    archive_to = os.path.basename(new_source.strip(os.sep))
    shutil.make_archive(name, format, archive_from, archive_to)
    shutil.move(f'{name}.{format}', destination)
    shutil.rmtree(new_source)

def pickup_count(base_url,post_transid):
    url = "{}/loyalty/orders/{}".format(base_url,post_transid)
    headers = {"invoice_number": post_transid}
    response = requests.get(url, headers = headers)
    total_picked_products = 0
    if response.status_code == 200:
        activities = response.json()
        for acitivity in activities['invoice']['line_items']:
            total_picked_products += acitivity['quantity']
    return total_picked_products

def upload_video(logger, trans_id, post_transid, images_path, video_path, customer_trans):
    if not os.path.exists(images_path):
        logger.info("      No DoorOpened Message")
        return 0
    images = [img for img in os.listdir(images_path) if img.endswith(".jpg")]
    if len(images) == 0:
        status = f' Discarding the Transaction: {post_transid}'
        threading.Thread(target=send_alert, args=(logger,config.vicki_app,status)).start()
        return 0

    images.sort(key=lambda x: int(x.split('.')[0]))
    frames = [os.path.join(images_path, image) for image in images]

    clip = moviepy.video.io.ImageSequenceClip.ImageSequenceClip(frames, fps=10)
    clip.write_videofile(video_path, verbose=False, logger = None)
            
    logger.info("	Video created: {} frames for {}".format(len(images), post_transid))
    
    #os.makedirs(os.path.join(config.base_path, 'post_archive', trans_id), exist_ok= True)
    frames_path = '{}archive/{}/Frames'.format(config.base_path, trans_id)

    if os.path.exists(frames_path):os.system('rm -r {}'.format(frames_path))
    
    make_archive('archive/{}'.format(trans_id), 'post_archive/{}.zip'.format(post_transid))
    
    fileobj = open('post_archive/{}.zip'.format(post_transid), 'rb')
    logger.info("      Uploading Archive...")
    
    file_path = 'post_archive/{}.zip'.format(post_transid)
    file_size_bytes = os.path.getsize(file_path)
    file_size_mb = file_size_bytes / (1024 * 1024)

    base_url, machine_id, machine_token, machine_api_key = login.get_custom_machine_settings(config.vicki_app, logger)
    access_token = login.get_current_access_token(base_url, machine_id, machine_token, machine_api_key, logger)
    
    # products_count = pickup_count(base_url,post_transid)
    try:
        if customer_trans == 'False':
            url = "{}/loyalty/upload-media/cv?media_event_type=TECHNICIAN_MODE&invoice_id={}".format(base_url,post_transid)
            headers = {"Authorization": "Bearer {}".format(access_token)}
            response_media = requests.post(url, files = {'file':fileobj}, headers=headers)
        else:
            # if products_count >= 3:
            #     url = "https://ist873mo99.execute-api.us-west-2.amazonaws.com/prod/upload"
            #     headers = {"Content-Type": "application/zip", "file-name": f'{post_transid}.zip'}
            #     with open(f'post_archive/{post_transid}.zip', "rb") as file_data:
            #         response_media = requests.post(url, headers=headers, data=file_data)
            # else:
            url = "{}/loyalty/upload-media/cv?media_event_type=COMPUTER_VISION&invoice_id={}".format(base_url,post_transid)
            headers = {"Authorization": "Bearer {}".format(access_token)}
            response_media = requests.post(url, files = {'file':fileobj}, headers=headers)

        if response_media.status_code == 200:
            status = f' Media Uploaded Successfully (Transaction: {post_transid}) File-size: {file_size_mb:.2f} MB'
            logger.info("      Uploaded {}".format(post_transid))
            os.system("rm -r post_archive/{}.zip".format(post_transid))
            logger.info("      Cleaned Transaction")
            threading.Thread(target=send_alert, args=(logger,config.vicki_app,status,False)).start()
        elif response_media.status_code == 504:
            status = f'Endpoint Time-out Error for Media Upload ({response_media.status_code}) (Transaction: {post_transid})'
            logger.info("      {}".format(response_media))
            logger.info("      Uploading media - FAILED for {}".format(post_transid))
            os.system("mv post_archive/{}.zip temp/".format(post_transid))
            threading.Thread(target=send_alert, args=(logger,config.vicki_app,status)).start()
        else:
            status = f'Media Upload Failed (Transaction: {post_transid})'
            logger.info("      {}".format(response_media))
            logger.info("      Uploading media - FAILED for {}".format(post_transid))
            logger.info("      Archiving Transaction / For batch processing")
            logger.info("   Finished Current Transaction")
            threading.Thread(target=send_alert, args=(logger,config.vicki_app,status)).start()
    except Exception as e:
        logger.info("      Uploading media-Failed")
        # logger.info(response_media.json())
        # logger.info(traceback.format_exc())      