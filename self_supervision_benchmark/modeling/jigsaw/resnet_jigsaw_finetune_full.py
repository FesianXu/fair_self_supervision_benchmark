# Copyright (c) Facebook, Inc. and its affiliates.
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.
#
################################################################################

"""
ResNet-50 model for testing feature quality of Jigsaw approach pre-training.
Transfer Task - Full Finetuning on VOC07 dataset.
"""

from __future__ import absolute_import
from __future__ import unicode_literals
from __future__ import print_function
from __future__ import division

import logging

from self_supervision_benchmark.core.config import config as cfg
from self_supervision_benchmark.modeling.jigsaw.siamese_model_helper import \
    SiameseModelHelper

# create the logger
logger = logging.getLogger(__name__)

# For more depths, add the depth config here: <depth>: (n1, n2, n3, n4) where
# n{} is the number of resnet blocks per stage. For the purpose of this
# benchmark, we experiment with ResNet-50 only.
BLOCK_CONFIG = {
    50: (3, 4, 6, 3),
}


def create_model(model, data, labels, split):
    siamese_model_helper = SiameseModelHelper(model, split)
    dataset = cfg.DATASET
    logger.info(' | ResNet-{} {}'.format(cfg.MODEL.DEPTH, dataset))
    assert cfg.MODEL.DEPTH in BLOCK_CONFIG.keys(), \
        'Block config is not defined for specified model depth. Please check.'
    (n1, n2, n3, n4) = BLOCK_CONFIG[cfg.MODEL.DEPTH]

    num_features = 2048
    residual_block = siamese_model_helper.bottleneck_block
    num_classes = cfg.MODEL.NUM_CLASSES

    test_mode = False
    if split in ['test', 'val']:
        test_mode = True

    ################################ conv1 #####################################
    conv_blob = model.Conv(
        'data', 'conv1_s0', 3, 64, 7, stride=2, pad=3,
        weight_init=('MSRAFill', {}),
        bias_init=('ConstantFill', {'value': 0.0}), no_bias=1
    )
    bn_blob = model.SpatialBN(
        conv_blob, 'res_conv1_bn_s0',
        64, epsilon=cfg.MODEL.BN_EPSILON,
        momentum=cfg.MODEL.BN_MOMENTUM, is_test=test_mode,
    )
    if cfg.MODEL.BN_NO_SCALE_SHIFT:
        model.param_init_net.ConstantFill(
            [bn_blob + '_s'], bn_blob + '_s', value=1.0
        )
        model.param_init_net.ConstantFill(
            [bn_blob + '_b'], bn_blob + '_b', value=0.0
        )
    relu_blob = model.Relu(bn_blob, bn_blob)

    ################################ pool1 #####################################
    max_pool = model.MaxPool(relu_blob, 'pool1_s0', kernel=3, stride=2, pad=1)

    ################################ stage2 ####################################
    blob_in, dim_in = siamese_model_helper.residual_layer(
        residual_block, max_pool, 64, 256, stride=1, num_blocks=n1,
        prefix='res2', index=0, dim_inner=64,
    )
    ################################ stage3 ####################################
    blob_in, dim_in = siamese_model_helper.residual_layer(
        residual_block, blob_in, dim_in, 512, stride=2, num_blocks=n2,
        prefix='res3', index=0, dim_inner=128,
    )
    ################################ stage4 ####################################
    blob_in, dim_in = siamese_model_helper.residual_layer(
        residual_block, blob_in, dim_in, 1024, stride=2, num_blocks=n3,
        prefix='res4', index=0, dim_inner=256,
    )
    ################################ stage5 ####################################
    blob_in, dim_in = siamese_model_helper.residual_layer(
        residual_block, blob_in, dim_in, num_features, stride=2, num_blocks=n4,
        prefix='res5', index=0, dim_inner=512,
    )

    ################################ pool5 #####################################
    pool_blob = model.AveragePool(blob_in, 'pool5_s0', kernel=7, stride=1)
    bn_c5 = model.SpatialBN(
        pool_blob, pool_blob + '_bn', num_features,
        epsilon=cfg.MODEL.BN_EPSILON, momentum=cfg.MODEL.BN_MOMENTUM,
        is_test=test_mode
    )
    if cfg.MODEL.BN_NO_SCALE_SHIFT:
        model.param_init_net.ConstantFill([bn_c5 + '_s'], bn_c5 + '_s', value=1.0)
        model.param_init_net.ConstantFill([bn_c5 + '_b'], bn_c5 + '_b', value=0.0)

    ################################## fc ######################################
    blob_out = model.FC(
        bn_c5, 'fc_c5', num_features, num_classes,
        weight_init=('GaussianFill', {'std': 0.01}),
        bias_init=('ConstantFill', {'value': 0.0}),
    )

    ################################ sigmoid ###################################
    model.net.Alias(blob_out, 'pred')
    sigmoid = model.net.Sigmoid('pred', 'sigmoid')
    scale = 1. / cfg.NUM_DEVICES

    if split == 'train':
        loss = model.net.SigmoidCrossEntropyLoss(
            ['pred', labels], 'loss', scale=scale
        )
    elif split in ['test', 'val']:
        loss = None
    return model, sigmoid, loss
