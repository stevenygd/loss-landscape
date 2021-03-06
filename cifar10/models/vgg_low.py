"""
    VGG model definition
    ported from https://github.com/pytorch/vision/blob/master/torchvision/models/vgg.py
"""

import math
import torch
import torch.nn as nn
import torchvision.transforms as transforms
from .quantizer import BlockQuantizer, FixedQuantizer, DynamicFixedQuantizer

__all__ = ['VGG16LP', 'VGG16BNLP', 'VGG19LP', 'VGG19BNLP']


def make_layers(cfg, quant, batch_norm=False):
    layers = list()
    in_channels = 3
    n = 1
    for v in cfg:
        if v == 'M':
            layers += [nn.MaxPool2d(kernel_size=2, stride=2)]
        else:
            use_quant = v[-1] != 'N'
            filters = int(v) if use_quant else int(v[:-1])
            conv2d = nn.Conv2d(in_channels, filters, kernel_size=3, padding=1)
            if batch_norm:
                layers += [conv2d, nn.BatchNorm2d(filters), nn.ReLU(inplace=True)]
            else:
                layers += [conv2d, nn.ReLU(inplace=True)]
            if use_quant: layers += [quant("conv{}".format(n))]
            n += 1
            in_channels = filters
    return nn.Sequential(*layers)


cfg = {
    16: ['64', '64', 'M', '128', '128', 'M', '256', '256', '256', 'M', '512', '512', '512', 'M', '512', '512', '512', 'M'],
    19: [64, 64, 'M', 128, 128, 'M', 256, 256, 256, 256, 'M', 512, 512, 512, 512, 'M',
         512, 512, 512, 512, 'M'],
}

class VGG16LP(nn.Module):

    def __init__(self, wl_activate=8, fl_activate=8, wl_error=8, fl_error=8, layer_type="block", quant_type="stochastic",
                 quantize_backward=False, num_classes=10, depth=16, batch_norm=False, writer=None):
        super(VGG16LP, self).__init__()
        assert layer_type in ["block", "fixed"]
        assert quant_type in ["nearest", "stochastic"]
        if layer_type == "block":
            quant = lambda name : BlockQuantizer(wl_activate, wl_error, "stochastic", quantize_backward)
            self.w_quant = BlockQuantizer(wl_activate, wl_error, "stochastic", quantize_backward)
        elif layer_type == "fixed":
            quant = lambda name : FixedQuantizer(wl_activate, fl_activate, "stochastic", quantize_backward)
            self.w_quant = FixedQuantizer(wl_activate, fl_activate, "stochastic", quantize_backward)
        else:
            raise Exception("Invalid layer-type:%s"%layer_type)

        self.features = make_layers(cfg[depth], quant, batch_norm)
        self.classifier = nn.Sequential(
            nn.Dropout(),
            nn.Linear(512, 512),
            nn.ReLU(True),
            quant("fc1"),
            nn.Dropout(),
            nn.Linear(512, 512),
            nn.ReLU(True),
            quant("fc2"),
            nn.Linear(512, num_classes),
        )
        for m in self.modules():
            if isinstance(m, nn.Conv2d):
                n = m.kernel_size[0] * m.kernel_size[1] * m.out_channels
                m.weight.data.normal_(0, math.sqrt(2. / n))
                m.bias.data.zero_()

    def forward(self, x):
        x = self.features(x)
        x = x.view(x.size(0), -1)
        x = self.classifier(x)
        return x

    def eval(self):
        # with torch.no_grad():
        #     for p in self.parameters():
        #         p.data = self.w_quant(p.data)
        return super(VGG16LP, self).eval()

