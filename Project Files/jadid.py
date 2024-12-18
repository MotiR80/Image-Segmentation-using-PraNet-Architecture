# -*- coding: utf-8 -*-
"""jadid.ipynb

Automatically generated by Colaboratory.

Original file is located at
    https://colab.research.google.com/drive/1RuKeQ_PntqOI0mOt5NhL_xX2CoAR8RRW

# **Download dataset and unzip it**
----> **Run this code just one time!** <----
"""

from google.colab import drive
drive.mount('/content/drive/')

!wget https://datasets.simula.no/downloads/kvasir-seg.zip
!unzip kvasir-seg.zip

!git clone https://github.com/Thehunk1206/PRANet-Polyps-Segmentation.git
!cp -r /content/PRANet-Polyps-Segmentation/model  .
!cp -r /content/PRANet-Polyps-Segmentation/utils  .
!rm -rf /content/PRANet-Polyps-Segmentation
!mkdir results

"""# **Import Libaries**"""

from datetime import datetime
from time import time
from tqdm import tqdm
import argparse
import sys
import os
from utils.losses import WBCEDICELoss
from utils.dataset import TfdataPipeline
from model.PRA_net import PRAnet
import tensorflow as tf
from utils.segmentation_metric import dice_coef, iou_metric, MAE, WFbetaMetric, SMeasure, Emeasure
from tensorflow.python.data.ops.dataset_ops import DatasetV2
from tensorflow.keras import models
import numpy as np
import random
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
from tensorflow.python.ops.image_ops_impl import ResizeMethod
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3'

"""# **Building Model And Training**"""

tf.random.set_seed(41)


def process_output(x: tf.Tensor, threshold:float = None):


    x = tf.sigmoid(x)
    if threshold:
        x = tf.cast(tf.math.greater(x, threshold), tf.float32)
    x = x * 255.0
    return x


def train(
    dataset_dir: str,
    trained_model_dir: str,
    img_size: int = 352,
    batch_size: int = 8,
    epochs: int = 25,
    lr: float = 1e-3,
    gclip: float = 1.0,
    dataset_split: float = 0.1,
    backbone_trainable: bool = True,
    backbone_arc:str = 'resnet50',
    logdir: str = "logs/",
):
    assert os.path.isdir(dataset_dir)
    if backbone_arc == 'mobilenetv2' and img_size > 224:
        tf.print(f"For backbone {backbone_arc} inputsize should be 32 < inputsize <=224")
        sys.exit()

    if not os.path.exists(dataset_dir):
        print(f"No dir named {dataset_dir} exist")
        sys.exit()

    if not os.path.exists(trained_model_dir):
        os.mkdir(path=trained_model_dir)

    # instantiate tf.summary writer
    logsdir = logdir + "PRAnet/" + "PRAnet_"+backbone_arc+datetime.now().strftime("%Y%m%d-%H%M%S")
    train_writer = tf.summary.create_file_writer(logsdir + "/train/")
    val_writer = tf.summary.create_file_writer(logsdir + "/val/")

    # initialize tf.data pipeline
    tf_datapipeline = TfdataPipeline(
        BASE_DATASET_DIR=dataset_dir,
        IMG_H=img_size,
        IMG_W=img_size,
        batch_size=batch_size,
        split=dataset_split
    )
    train_data = tf_datapipeline.data_loader(dataset_type='train')
    val_data = tf_datapipeline.data_loader(dataset_type='valid')

    # instantiate optimizer
    optimizer = tf.keras.optimizers.Adam(
        learning_rate=lr,
    )

    # instantiate loss function
    loss_fn = WBCEDICELoss(name='w_bce_dice_loss')


    # instantiate model (PRAnet)
    pranet = PRAnet(
        IMG_H=img_size,
        IMG_W=img_size,
        filters=32,
        backbone_arch=backbone_arc,
        backbone_trainable=backbone_trainable
    )

    # compile the model
    pranet.compile(
        optimizer=optimizer,
        loss=loss_fn,
    )
    tf.print(pranet.build_graph(inshape=(img_size, img_size, 3)).summary())
    tf.print("==========Model configs==========")
    tf.print(
        f"Training and validating PRAnet for {epochs} epochs \nlearing_rate: {lr} \nInput shape:({img_size},{img_size},3) \nBatch size: {batch_size} \nBackbone arc: {backbone_arc} \nBackbone Trainable: {backbone_trainable}"
    )
    # train for epochs
    for e in range(epochs):
        t = time()

        for (x_train_img, y_train_mask) in tqdm(train_data, unit='steps', desc='training...', colour='red'):
            train_loss, train_dice, train_iou = pranet.train_step(
                x_img=x_train_img, y_mask=y_train_mask, gclip=gclip)

        for (x_val_img, y_val_mask) in tqdm(val_data, unit='steps', desc='Validating...', colour='green'):
            val_loss, val_dice, val_iou = pranet.test_step(x_img=x_val_img, y_mask=y_val_mask)

        tf.print(
            "ETA:{} - epoch: {} - loss: {} - dice: {} - IoU: {} - val_loss: {} - val_dice: {} - val_IoU: {} \n".format(
                round((time() - t)/60, 2), (e+1), train_loss, train_dice, train_iou, val_loss, val_dice, val_iou)
            )


        tf.print("Writing to Tensorboard...")
        lateral_out_sg, lateral_out_s4, lateral_out_s3, lateral_out_s2 = pranet(x_val_img, training=False)
        lateral_out_sg = process_output(lateral_out_sg)
        lateral_out_s4 = process_output(lateral_out_s4)
        lateral_out_s3 = process_output(lateral_out_s3)
        lateral_out_s2 = process_output(lateral_out_s2, threshold = 0.3)


        with train_writer.as_default():
            tf.summary.scalar(name='train_loss', data=train_loss, step=e+1)
            tf.summary.scalar(name='dice', data = train_dice, step=e+1)
            tf.summary.scalar(name='iou', data = train_iou, step=e+1)


        with val_writer.as_default():
            tf.summary.scalar(name='val_loss', data=val_loss, step=e+1)
            tf.summary.scalar(name='val_dice', data=val_dice, step=e+1)
            tf.summary.scalar(name='val_dice', data=val_iou, step=e+1)
            tf.summary.image(name='Y_mask', data=y_val_mask*255, step=e+1, max_outputs=batch_size, description='Val data')
            tf.summary.image(name='Global S Map', data=lateral_out_sg, step=e+1, max_outputs=batch_size, description='Val data')
            tf.summary.image(name='S4 Map', data=lateral_out_s4, step=e+1, max_outputs=batch_size, description='Val data')
            tf.summary.image(name='S3 Map', data=lateral_out_s3, step=e+1, max_outputs=batch_size, description='Val data')
            tf.summary.image(name='S2 Map', data=lateral_out_s2, step=e+1, max_outputs=batch_size, description='Val data')

        if (e+1)%5 == 0:
            tf.print(
                f"Saving model at {trained_model_dir}..."
            )
            pranet.save(f"{trained_model_dir}pranet_{backbone_arc}", save_format='tf')
            tf.print(f"model saved at {trained_model_dir}")

with tf.device('/device:GPU:0'):
  if __name__ == "__main__":
      train(
          dataset_dir="Kvasir-SEG/",
          trained_model_dir="/content/drive/MyDrive/trained_model/",
          img_size=352,
          batch_size=16,
          epochs=25,
          lr=1e-4,
          gclip=0.5
      )

"""# **Prediction**

"""

def get_model(model_path: str):
    assert isinstance(model_path, str)

    tf.print(
        "[info] loading model from disk...."
    )
    model = models.load_model(model_path)

    tf.print(
        "loaded model {}".format(model)
    )
    return model


def datapipeline(dataset_path: str, imgsize: int = 352) -> DatasetV2:
    assert isinstance(dataset_path, str)

    tfpipeline = TfdataPipeline(
        BASE_DATASET_DIR=dataset_path, IMG_H=imgsize, IMG_W=imgsize, batch_size=1)
    test_data = tfpipeline.data_loader(dataset_type='test')

    return test_data


def run_test(
    model_path: str,
    imgsize: int = 352,
    dataset_path: str = 'polyps_dataset/',
    threshold: float = 0.5
):
    assert os.path.exists(model_path)
    assert os.path.exists(dataset_path)
    assert 1.0 > threshold > 0.0

    pranet = get_model(model_path=model_path)
    test_data = datapipeline(dataset_path=dataset_path, imgsize=imgsize)

    # initialize metrics
    wfb_metric = WFbetaMetric()
    smeasure_metric = SMeasure()
    emeasure_metric = Emeasure()
    # collect metric for individual test data to average it later
    dice_coefs = []
    ious = []
    wfbs = []
    smeasures = []
    emeasures = []
    maes = []
    runtimes = []

    for (image, mask) in tqdm(test_data, desc='Testing..', unit='steps', colour='green'):
        start = time()
        outs = pranet(image)
        end = time()
        # squesh the out put between 0-1
        final_out = tf.sigmoid(outs[-1])
        # convert the out map to binary map
        final_out = tf.cast(tf.math.greater(final_out, 0.5), tf.float32)

        total_time = round((end - start)*1000, ndigits=2)

        dice = dice_coef(y_mask=mask, y_pred=final_out)
        iou = iou_metric(y_mask=mask, y_pred=final_out)
        mae = MAE(y_mask=mask, y_pred= final_out)
        wfb = wfb_metric(y_mask=mask, y_pred=final_out)
        smeasure = smeasure_metric(y_mask=mask, y_pred=final_out)
        emeasure = emeasure_metric(y_mask=mask, y_pred= final_out)

        dice_coefs.append(dice)
        ious.append(iou)
        maes.append(mae)
        wfbs.append(wfb)
        smeasures.append(smeasure)
        emeasures.append(emeasure)
        runtimes.append(total_time)

    mean_dice = sum(dice_coefs)/len(dice_coefs)
    mean_iou = sum(ious)/len(ious)
    mean_mae = sum(maes)/len(maes)
    mean_wfb = sum(wfbs)/len(wfbs)
    mean_smeasure = sum(smeasures)/len(smeasures)
    mean_emeasure = sum(emeasures)/len(emeasures)
    mean_runtime = sum(runtimes[3:]) / len(runtimes[3:])
    tf.print(
        f"Average runtime of model: {mean_runtime}ms \n",
        f"Mean IoU: {mean_iou}\n",
        f"Mean Dice coef: {mean_dice}\n",
        f"Mean wfb: {mean_wfb}\n",
        f"Mean Smeasure: {mean_smeasure}\n",
        f"Mean Emeasure: {mean_emeasure}\n",
        f"MAE: {mean_mae}\n",
    )

with tf.device('/device:GPU:0'):
  if __name__ == "__main__":
      run_test(
          model_path='/content/drive/MyDrive/trained_model/pranet_resnet50',
          dataset_path='Kvasir-SEG/',
          imgsize=256
      )

"""# **Save Results**"""

def read_image(path: str, img_size: int = 352) -> tf.Tensor:
    image_raw = tf.io.read_file(path)
    original_image = tf.io.decode_jpeg(image_raw, channels=3)
    original_image = tf.cast(original_image, dtype=tf.float32)
    original_image = original_image/255.0

    resized_image = tf.image.resize(original_image, [img_size, img_size])
    resized_image = tf.expand_dims(resized_image, axis=0)

    return resized_image, original_image

def read_mask(path: str, img_size: int = 352) -> tf.Tensor:
    image_raw = tf.io.read_file(path)
    mask = tf.io.decode_jpeg(image_raw, channels=1)
    mask = tf.cast(mask, dtype=tf.float32)

    return mask


def process_output(x: tf.Tensor, original_img: tf.Tensor, threshold: float = None) -> tf.Tensor:
    x = tf.sigmoid(x)

    if threshold:
        x = tf.cast(tf.math.greater(x, threshold), tf.float32)

    x = tf.squeeze(x, axis=0)
    x = tf.image.resize(x, [original_img.shape[0], original_img.shape[1]], ResizeMethod.BICUBIC)
    # we use tf.tile to make multiple copy of output single channel image
    mutiple_const = tf.constant([1,1,3]) # [1,1,3] h(1)xw(1)xc(3)
    x = tf.tile(x,mutiple_const)

    return x


def get_model(model_path: str):
    assert isinstance(model_path, str)

    tf.print(
        "[info] loading model from disk...."
    )
    model = models.load_model(model_path)

    tf.print(
        "[info] loaded model"
    )
    return model

def select_random_images(directory, percentage=0.1):
    if not os.path.exists(directory) or not os.path.isdir(directory):
        raise ValueError("The provided path is not valid or is not a directory.")

    images_dir = os.path.join(directory, 'images')
    masks_dir = os.path.join(directory, 'masks')

    image_files = [f for f in os.listdir(images_dir) if f.lower().endswith(('.png', '.jpg', '.jpeg'))]
    num_images_to_select = int(len(image_files) * percentage)

    if num_images_to_select == 0:
        raise ValueError("The number of images to select is zero.")

    selected_images = random.sample(image_files, num_images_to_select)
    images_paths = [os.path.join(images_dir, img) for img in selected_images]
    masks_paths = [os.path.join(masks_dir, img) for img in selected_images]

    return images_paths, masks_paths

def vis_predicted_mask(*images: tf.Tensor):
    plt.figure(figsize=(20, 10))
    grid_spec = gridspec.GridSpec(2, 3, width_ratios=[3, 3, 3])

    plt.subplot(grid_spec[0])
    plt.imshow(images[0])
    plt.axis('off')
    plt.title("Original Image")

    plt.subplot(grid_spec[1])
    plt.imshow(images[5], 'gray')
    plt.axis('off')
    plt.title("True mask")

    plt.subplot(grid_spec[2])
    plt.imshow(images[1])
    plt.axis('off')
    plt.title("Predicted Mask")

    plt.subplot(grid_spec[3])
    plt.imshow(images[2])
    plt.axis('off')
    plt.title("Global S Map")

    plt.subplot(grid_spec[4])
    plt.imshow(images[3])
    plt.axis('off')
    plt.title("Side Map 4")

    plt.subplot(grid_spec[5])
    plt.imshow(images[4])
    plt.axis('off')
    plt.title("Side Map 3")

    plt.grid('off')
    plt.savefig(f"results/detection_{time()}.jpg")


def run(
    model_path: str,
    dataset_path: str,
    imgsize: int = 352,
    threshold: float = 0.5
):
    assert os.path.exists(model_path)
    assert os.path.exists(dataset_path)
    assert 1.0 > threshold > 0.0

    pranet = get_model(model_path=model_path)

    images_path, masks_path = select_random_images(dataset_path, .05)

    for image_path, mask_path in zip(images_path, masks_path):
      input_image, original_image = read_image(
          path=image_path, img_size=imgsize)

      true_mask = read_mask(path=mask_path, img_size=imgsize)

      tf.print("[info] Computing output mask..")
      start = time()
      outs = pranet(input_image)
      end = time()
      sg, s4, s3, final_out = outs
      final_out = process_output(final_out, original_img=original_image, threshold=threshold)
      sg = process_output(sg, original_img=original_image)
      s4 = process_output(s4, original_img=original_image)
      s3 = process_output(s3, original_img=original_image)


      total_time = round((end - start)*1000, ndigits=2)
      tf.print(f"Total runtime of model: {total_time}ms")


      vis_predicted_mask(original_image, final_out, sg, s4, s3, true_mask)
with tf.device('/device:GPU:0'):
  if __name__ == "__main__":
    run(
        model_path='/content/drive/MyDrive/trained_model/pranet_resnet50',
        dataset_path='/content/Kvasir-SEG',
        imgsize=256
    )

"""# **Download The Results**"""

from google.colab import files
!zip results.zip results/*
files.download('results.zip')