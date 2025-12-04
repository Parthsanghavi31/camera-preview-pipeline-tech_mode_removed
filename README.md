# Camera-preview-pipeline
The Camera Preview Pipeline monitor the retail machine's transactions, detecting when door is opened and locked while recording transaction details. Once an OrderSettled message is received, the recorded transaction is finalized and uploaded to the designated endpoint

# 1. Steps to setup pipeline
## Step 1.1 Install dependencies and deploy pipeline
Run the following command
```
bash scripts/setup.sh
```
## Step 1.2 Setup the reboot
Run the following command
```
bash scripts/setup_reboot.sh
```
# 2. Check the status of the pipeline
Run the following command
```
bash bin/cv_status.sh
```
NOTE : You can run the other scripts inside the bin folder to stop, restart, disable, enable the pipeline

