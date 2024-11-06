#############################################
# Object detection - YOLO - OpenCV
# Author : Arun Ponnusamy   (July 16, 2018)
# Website : http://www.arunponnusamy.com
############################################

import boto3
import botocore
import json
import logging
import os

from urllib.parse import urlparse

import cv2
import numpy

# Copied from: https://stackoverflow.com/a/42641363
class S3Url(object):
    """
    >>> s = S3Url("s3://bucket/hello/world")
    >>> s.bucket
    'bucket'
    >>> s.key
    'hello/world'
    >>> s.url
    's3://bucket/hello/world'

    >>> s = S3Url("s3://bucket/hello/world?qwe1=3#ddd")
    >>> s.bucket
    'bucket'
    >>> s.key
    'hello/world?qwe1=3#ddd'
    >>> s.url
    's3://bucket/hello/world?qwe1=3#ddd'

    >>> s = S3Url("s3://bucket/hello/world#foo?bar=2")
    >>> s.key
    'hello/world#foo?bar=2'
    >>> s.url
    's3://bucket/hello/world#foo?bar=2'
    """

    def __init__(self, url):
        self._parsed = urlparse(url, allow_fragments=False)

    @property
    def bucket(self):
        return self._parsed.netloc

    @property
    def key(self):
        if self._parsed.query:
            return self._parsed.path.lstrip('/') + '?' + self._parsed.query
        else:
            return self._parsed.path.lstrip('/')

    @property
    def url(self):
        return self._parsed.geturl()

def get_output_layers(net):
    layer_names = net.getLayerNames()
    output_layers = [layer_names[i - 1] for i in net.getUnconnectedOutLayers()]
    return output_layers

def draw_blur(img, classes, class_id, COLORS, confidence, x, y, x_plus_w, y_plus_h):
    label = str(classes[class_id])

    color = COLORS[class_id]
    if label in ['person', 'car', 'bus', 'truck']:        
        blurval = 9
        if int(y_plus_h -y) > 100 or int(x_plus_w -x) > 100:
            blurval = 11
        if int(y_plus_h -y) > 200 or int(x_plus_w -x) > 200:
            blurval = 13
        if int(y_plus_h -y) > 300 or int(x_plus_w -x) > 300:
            blurval = 27
        
        img[int(y):int(y_plus_h), int(x):int(x_plus_w)] = cv2.medianBlur(img[int(y):int(y_plus_h), int(x):int(x_plus_w)] ,blurval)

def lambda_handler(event, context):
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    logger.debug('event parameter: {}'.format(event))
    logger.debug('context parameter: {}'.format(context))

    # event['image'] = event.get('image', "/tmp/original-image.jpg")
    # event['filtered_image'] = event.get('filtered_image', "/tmp/filtered-image.jpg")
    event['config'] = "/var/task/yolov3.cfg"
    event['weights'] = "/var/task/yolov3.weights"
    event['classes'] = "/var/task/yolov3.txt"

    LOCAL_FILE_ORIGINAL_IMAGE = "/tmp/original-image.jpg"
    LOCAL_FILE_FILTERED_IMAGE = "/tmp/filtered-image.jpg"

    if 'image' not in event or 'filtered_image' not in event:
        return {
            "statusCode": 500,
            "body": json.dumps({
                "message": "Input parameters 'image' or 'filtered_image' missing. Exiting.",
            }),
        }

    logger.info('Anonymizing image: ' + event['image'])
    logger.info('Anonymized image will be stored in: ' + event['filtered_image'])

    parsed_image_url = urlparse(event['image'])
    if parsed_image_url.scheme != 's3':
        return {
            "statusCode": 500,
            "body": json.dumps({
                "message": "Provided URL not an S3 URL: " + event['image'],
            }),
        }

    parsed_filtered_image_url = urlparse(event['filtered_image'])
    if parsed_filtered_image_url.scheme != 's3':
        return {
            "statusCode": 500,
            "body": json.dumps({
                "message": "Provided URL not an S3 URL: " + event['filtered_image'],
            }),
        }


    s3_image = S3Url(event['image'])
    s3_filtered_image = S3Url(event['filtered_image'])

    s3 = boto3.resource('s3')
    try:
        s3.Bucket(s3_image.bucket).download_file(s3_image.key, LOCAL_FILE_ORIGINAL_IMAGE)
        logger.info('Sucessfully downloaded image: ' + event['image'])
    except botocore.exceptions.ClientError as e:
        message = "The object could not be downloaded: " + event['image'],
        if e.response['Error']['Code'] == "404":
            message = "The object does not exist: " + event['image']

        return {
            "statusCode": e.response['Error']['Code'],
            "body": json.dumps({
                "message": message,
            }),
        }

    logger.debug('Using OpenCV on image: ' + event['image'])
    image = cv2.imread(LOCAL_FILE_ORIGINAL_IMAGE)

    Width = image.shape[1]
    Height = image.shape[0]
    scale = 0.00392

    classes = None

    with open(event['classes'], 'r') as f:
        classes = [line.strip() for line in f.readlines()]

    COLORS = numpy.random.uniform(0, 255, size=(len(classes), 3))

    net = cv2.dnn.readNet(event['weights'], event['config'])

    blob = cv2.dnn.blobFromImage(image, scale, (416,416), (0,0,0), True, crop=False)

    net.setInput(blob)

    outs = net.forward(get_output_layers(net))

    class_ids = []
    confidences = []
    boxes = []
    conf_threshold = 0.5
    nms_threshold = 0.4

    for out in outs:
        for detection in out:
            scores = detection[5:]
            class_id = numpy.argmax(scores)
            confidence = scores[class_id]
            if confidence > 0.5:
                center_x = int(detection[0] * Width)
                center_y = int(detection[1] * Height)
                w = int(detection[2] * Width)
                h = int(detection[3] * Height)
                x = center_x - w / 2
                y = center_y - h / 2
                class_ids.append(class_id)
                confidences.append(float(confidence))
                boxes.append([x, y, w, h])

    indices = cv2.dnn.NMSBoxes(boxes, confidences, conf_threshold, nms_threshold)

    for i in indices:
        box = boxes[i]
        x = box[0]
        y = box[1]
        w = box[2]
        h = box[3]
        draw_blur(image, classes, class_ids[i], COLORS, confidences[i], round(x), round(y), round(x+w), round(y+h))
    
    cv2.imwrite(LOCAL_FILE_FILTERED_IMAGE, image)
    s3 = boto3.client('s3')
    try:
        response = s3.upload_file(LOCAL_FILE_FILTERED_IMAGE, s3_filtered_image.bucket, s3_filtered_image.key)
        logger.info('Sucessfully uploaded image to: ' + event['filtered_image'])
    except botocore.exceptions.ClientError as e:
        logging.error(e)
        return {
            "statusCode": e.response['Error']['Code'],
            "body": json.dumps({
                "message": "Failed to uploaded: " + event['filtered_image'],
            }),
        }

    return {
        "statusCode": 200,
        "body": json.dumps({
            "message": "image uploaded to as: " + event['filtered_image'],
        }),
    }
