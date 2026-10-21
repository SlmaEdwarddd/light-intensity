from ximea import xiapi
import cv2
import time
import numpy as np

#create instance for first connected camera
cam = xiapi.Camera()

#start communication
#to open specific device, use:
#cam.open_device_by_SN('41305651')
#(open by serial number)
print('Opening first camera...')
cam.open_device()

#settings
cam.set_exposure(100000)
print('Exposure was set to %i us' %cam.get_exposure())

#create instance of Image to store image data and metadata
img = xiapi.Image()

#start data acquisition
print('Starting data acquisition...')
cam.start_acquisition()

# FPS calculation variables
frame_count = 0
start_time = time.time()
fps = 0

print('Camera view started. Press "q" to quit.')

while True:
    #get data and pass them from camera to img
    cam.get_image(img)

    #get raw data from camera
    data_raw = img.get_image_data_raw()

    # Convert raw data to numpy array and reshape
    data = np.frombuffer(data_raw, dtype=np.uint8)
    frame = data.reshape((img.height, img.width))

    # Calculate FPS
    frame_count += 1
    elapsed_time = time.time() - start_time
    if elapsed_time > 1:
        fps = frame_count / elapsed_time
        frame_count = 0
        start_time = time.time()

    # Convert grayscale to BGR for text display
    frame_bgr = cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)

    # Add FPS text to frame
    cv2.putText(frame_bgr, f'FPS: {fps:.2f}', (10, 30), 
                cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)

    # Display frame
    cv2.imshow('Camera View', frame_bgr)

    # Press 'q' to exit
    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

#stop data acquisition
print('Stopping acquisition...')
cam.stop_acquisition()

#stop communication
cam.close_device()

# Close camera window
cv2.destroyAllWindows()

print('Done.')

