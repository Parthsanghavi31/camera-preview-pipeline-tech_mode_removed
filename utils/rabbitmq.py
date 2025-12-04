import pika
import json
import time
import requests
import logging
import sys
from utils import config
import os
import threading
from utils.send_alert import send_alert
import subprocess

class MessageProcessor:
    def __init__(self, logger, pika_name, get_message_queue, send_message_queue, vicki_app, minutes_to_end_transcation, warning_message_time, message_timeout, pipeline_status_interval):
        self.logger = logger
        self.pika_name = pika_name
        self.get_message_queue = get_message_queue
        self.send_message_queue = send_message_queue
        self.vicki_app = vicki_app
        self.minutes_to_end_transcation = minutes_to_end_transcation
        self.warning_message_time = warning_message_time
        self.message_timeout = message_timeout

        self.get_message_channel, self.get_message_connection = None, None

        self.door_opened_time = None
        self.door_locked_sent = False
        self.warning_sent = False
        self.last_message_time = time.time()
        self.initial_time = time.time()
        self.pipeline_status_interval = pipeline_status_interval
        self.is_technician_trans = False

    def initialize_channel(self, pika_name, queue):
        credentials = pika.PlainCredentials(pika_name, pika_name)
        parameters = pika.ConnectionParameters('localhost', 5672, '/', credentials, heartbeat=0, blocked_connection_timeout=3000)
        connection = pika.BlockingConnection(parameters)
        channel = connection.channel()
        channel.queue_declare(queue=queue, durable=True)
        self.logger.info(f"RabbitMQ connection initialized for queue: {queue}")
        return channel, connection

    def message_callback(self, ch, method, properties, body):
        current_time = time.time()
        self.last_message_time = current_time  # Reset the message timeout timer
        try:
            message = json.loads(body)
            print(message)

            if message['cmd'] == "DoorOpened":
                if message["parm1"].split(":")[1] == "True":
                    self.door_opened_time = current_time
                    self.door_locked_sent = False
                    self.warning_sent = False
                    self.is_technician_trans = False
                    self.send_message_queue.put(message)
                else:
                    self.is_technician_trans = True

            elif message['cmd'] == "DoorLocked" and not self.door_locked_sent:
                if not self.is_technician_trans:
                    self.door_opened_time = None
                    self.send_message_queue.put(message)

            elif message['cmd'] == "OrderSettled": #or message['cmd'] == "Technician":
                self.door_opened_time = None
                self.send_message_queue.put(message)
            ch.basic_ack(delivery_tag=method.delivery_tag)  # Acknowledge the message

        except Exception as e:
            self.logger.error(f"Error processing message: {e}")
            ch.basic_nack(delivery_tag=method.delivery_tag, requeue=True)  # Nack the message to retry
    
    def ping_device_and_send_alert(self,host='192.168.1.140', timeout=1, count=5):
        
        response = subprocess.run(
            ["ping", "-c", str(count), "-W", str(timeout), host],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        if response.returncode == 1:
            status_message = f'Main Pi is not working'
            send_alert(self.logger, self.vicki_app, status_message)
        

    def process_messages(self):
        try:
            self.get_message_channel, self.get_message_connection = self.initialize_channel(self.pika_name, self.get_message_queue)

            self.get_message_channel.basic_consume(queue=self.get_message_queue, on_message_callback=self.message_callback)

            self.logger.info('Waiting for messages...')
            self.last_message_time = time.time()

            counter = 0
            while True:                

                self.get_message_channel.connection.process_data_events(time_limit=0.1)
                if counter %20 == 0:
                    current_time = time.time()
                    if current_time - self.last_message_time > self.message_timeout:
                        alert = 'Pipeline is not getting messages. Timeout detected.'
                        threading.Thread(target=send_alert, args=(self.logger,self.vicki_app,alert,)).start()
                        self.send_message_queue.put({'cmd':'Stop'})

                    if self.door_opened_time:
                        if current_time - self.door_opened_time > self.warning_message_time and not self.warning_sent:
                            warning_message = '    Door opened but not locked within 3 minutes.'
                            threading.Thread(target=send_alert, args=(self.logger, self.vicki_app, warning_message,)).start()
                            self.warning_sent = True

                        if current_time - self.door_opened_time > self.minutes_to_end_transcation and not self.door_locked_sent:
                            warning_message = '    Door opened but not locked within 5 minutes. Generating DoorLocked message.'
                            threading.Thread(target=send_alert, args=(self.logger, self.vicki_app, warning_message,)).start()
                            self.send_message_queue.put({'cmd':'DoorLocked'})
                            self.door_locked_sent = True
                            self.door_opened_time = None
                            self.warning_sent = False
                            self.last_message_time = current_time
                            
                    if current_time - self.initial_time >= self.pipeline_status_interval:
                        status_message = f'Monitoring the Camera preview Pipeline after every {int(self.pipeline_status_interval/3600)} hours, It is Up and Running'
                        threading.Thread(target=send_alert, args=(self.logger, self.vicki_app, status_message, False)).start()
                        threading.Thread(target=self.ping_device_and_send_alert, args=()).start()
                        self.initial_time = current_time

                counter +=1
        except Exception as e:
            self.logger.error(f"Error during message processing: {e}")
            self.send_message_queue.put({'cmd':'Stop'})
        finally:
            if self.get_message_channel:
                self.get_message_channel.close()

def message_processing(logger, pika_name, get_message_queue, send_message_queue, vicki_app, minutes_to_end_transcation, warning_message_time, message_timeout, pipeline_status_interval):
    processor = MessageProcessor(
                logger,
                pika_name,
                get_message_queue, 
                send_message_queue, 
                vicki_app, 
                minutes_to_end_transcation, 
                warning_message_time, 
                message_timeout,
                pipeline_status_interval
                
    )
    processor.process_messages()

