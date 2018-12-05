from __future__ import print_function
import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.autograd import Variable
import numpy as np
import math

# R = torch.rand(int(1e8)).cuda()

def _quantize_log(x, wl, fsr, base=math.sqrt(2)):
    sign  = torch.sign(x)
    min_x = float(fsr) - base ** wl
    max_x = float(fsr) - 1
    x     = torch.round(x.abs().log() / math.log(base))
    x     = torch.clamp(x, min_x, max_x)
    x     = (torch.ones_like(x) * base).pow(x.float()) * sign
    return x

class LogQuant(torch.autograd.Function):

    @staticmethod
    def forward(self, x, wl, fsr, base, cuda, quantize_backward=True):
        self.wl  = wl
        self.fsr = fsr
        self.base = base
        self.quantize_backward = quantize_backward
        return _quantize_log(x, wl, fsr, base=base)

    @staticmethod
    def backward(self, grad_output):
        grad_input = None
        print("DLDY:%s"%grad_output)
        if self.needs_input_grad[0]:
            if self.quantize_backward:
                grad_input = _quantize_log(grad_output, self.wl, self.fsr, base=self.base)
            else:
                grad_input = grad_input
        print("DLDX:%s"%grad_input)
        return grad_input, None, None, None, None

def add_r_(data):
    size = 1
    for n in data.size(): size *= n
    # start = np.random.randint(0, R.size(0)-size-1)
    # r = R[start:start+size]
    # r = r.view_as(data)

    r = torch.cuda.FloatTensor(data.size()).uniform_()
    data.add_(r)

def _round(data, sigma, t_min, t_max, mode, clip=True):
    """
    Quantzie a Tensor.
    """
    temp = data / sigma
    if mode=="nearest":
        temp = temp.round()
    elif mode=="stochastic":
        add_r_(temp)
        temp.floor_()
    else: raise ValueError("Invalid quantization mode: {}".format(mode))
    temp *= sigma
    if clip: temp.clamp_(t_min, t_max)
    return temp

class FixedPointRounding(torch.autograd.Function):

    @staticmethod
    def forward(self, x, wl, fl, mode, quantize_backward=True):
        self.wl = wl
        self.fl = fl
        self.mode = mode
        self.quantize_backward = quantize_backward
        if self.wl == -1: return x
        sigma = 2.**(-self.fl)
        t_max = 2.**(self.wl-self.fl-1) - sigma
        t_min = -2.**(self.wl-self.fl-1)
        return _round(x, sigma, t_min, t_max, mode)

    @staticmethod
    def backward(self, grad_output):
        grad_input = None

        if self.needs_input_grad[0]:
            if self.quantize_backward and self.wl > 0:
                sigma = 2.**(-self.fl)
                t_max = 2.**(self.wl-self.fl-1) - sigma
                t_min = -2.**(self.wl-self.fl-1)
                grad_input = _round(grad_output, sigma, t_min, t_max, self.mode)
            else:
                grad_input = grad_output

        return grad_input, None, None, None, None

def block_quantize(data, bits, mode, ebit=8):
    max_entry = torch.max(torch.abs(data)).item()
    if max_entry == 0: return data
    # floor because the leading virtual bit in float
    max_exponent = math.floor(math.log2(max_entry))
    max_exponent = min(max(max_exponent, -2**(ebit-1)), 2**(ebit-1)-1)
    i = data * 2**(-max_exponent+(bits-2))
    if mode == "stochastic":
        add_r_(i)
        i.floor_()
    elif mode == "nearest":
        i.round_()
    i.clamp_(-2**(bits-1), 2**(bits-1)-1)
    temp = i * 2**(max_exponent-(bits-2))
    return temp

class BlockRounding(torch.autograd.Function):
    @staticmethod
    def forward(self, x, forward_bits, mode, quantize_backward, backward_bits=None):
        self.backward_bits = backward_bits
        self.mode = mode
        self.quantize_backward = quantize_backward
        if forward_bits == -1: return x
        return block_quantize(x, forward_bits, self.mode)

    @staticmethod
    def backward(self, grad_output):
        if self.needs_input_grad[0]:
            if self.quantize_backward and self.backward_bits != -1:
                grad_input = block_quantize(grad_output, self.backward_bits, self.mode)
            else:
                grad_input = grad_output
        return grad_input, None, None, None, None

def rescale(data, sigma, bit, r_max):
    t_max = sigma*2.**(bit-1)-sigma
    t_min = -sigma*2.**(bit-1)
    size = 1
    for s in data.size(): size *= s
    overflow = float((torch.sum(data > t_max) + torch.sum(data < t_min)).data) / size
    underflow = float((torch.sum(data > 0.5*t_max) + torch.sum(data < 0.5*t_min)).data) /size
    if overflow > r_max:
        sigma *= 2
    elif underflow < r_max:
        sigma *= 0.5
    t_max = sigma*2.**(bit-1)-sigma
    t_min = -sigma*2.**(bit-1)
    return sigma, t_min, t_max

class DynamicFixedPoint(torch.autograd.Function):
    @staticmethod
    def forward(ctx, x, forward_bits, backward_bits, mode, quantize_backward, sigma_dict, r_max, writer=None, name=None, epoch=None):
        assert mode in ["stochastic", "nearest"]
        ctx.backward_bits = backward_bits
        ctx.mode = mode
        ctx.quantize_backward = quantize_backward
        ctx.r_max = r_max
        ctx.sigma_dict = sigma_dict
        ctx.writer = writer
        ctx.name = name
        ctx.epoch = epoch
        if forward_bits == -1: return x
        sigma = sigma_dict["forward"]
        #ctx.writer.add_histogram(ctx.name+"/activation-before", x.clone().cpu().numpy(), ctx.epoch)
        sigma, t_min, t_max = rescale(x, sigma, forward_bits, r_max)
        #ctx.writer.add_scalar(ctx.name+"/forward-sigma", sigma, ctx.epoch)
        sigma_dict["forward"] = sigma
        activations = _round(x, sigma, t_min, t_max, "stochastic")
        #ctx.writer.add_histogram(ctx.name+"/activation-after", activations.clone().cpu().numpy(), ctx.epoch)
        return activations

    @staticmethod
    def backward(ctx, grad_output):
        #ctx.writer.add_histogram(ctx.name+"/error-before", grad_output.clone().cpu().numpy(), ctx.epoch)
        if ctx.needs_input_grad[0]:
            if ctx.quantize_backward and ctx.backward_bits > 0:
                sigma = ctx.sigma_dict["backward"]
                sigma, t_min, t_max = rescale(grad_output, sigma, ctx.backward_bits, ctx.r_max)
                ctx.sigma_dict["backward"] = sigma
                #ctx.writer.add_scalar(ctx.name+"/back-sigma", sigma, ctx.epoch)
                grad_input = _round(grad_output, sigma, t_min, t_max, "stochastic")
                #ctx.writer.add_histogram(ctx.name+"/error-after", grad_input.clone().cpu().numpy(), ctx.epoch)
            else:
                grad_input = grad_output
        return grad_input, None, None, None, None, None, None, None, None, None

quantize_fixed = FixedPointRounding.apply
quantize_block = BlockRounding.apply
quantize_log = LogQuant.apply
quantize_dynamic = DynamicFixedPoint.apply

class DynamicFixedQuantizer(nn.Module):
    def __init__(self, forward_bits, backward_bits, mode, r_max, quantize_backward, writer, name):
        super(DynamicFixedQuantizer, self).__init__()
        self.mode = mode
        self.quantize_backward = quantize_backward
        self.forward_bits = forward_bits
        self.backward_bits = backward_bits
        self.r_max = r_max
        self.sigma_dict = {"forward":2.**(6-forward_bits),
                "backward":2.**(6-backward_bits)}
        self.writer = writer
        self.name = name
        self.epoch = 0

    def forward(self, x):
        self.epoch += 1
        return quantize_dynamic(x, self.forward_bits, self.backward_bits, self.mode,
                self.quantize_backward, self.sigma_dict, self.r_max, self.writer, self.name, self.epoch)

class BlockQuantizer(nn.Module):
    def __init__(self, wl_activate, wl_error, mode, quantize_backward):
        super(BlockQuantizer, self).__init__()
        self.wl_activate = wl_activate
        self.wl_error = wl_error
        self.mode = mode
        self.quantize_backward = quantize_backward

    def forward(self, x):
        return quantize_block(x, self.wl_activate, self.mode,
            self.quantize_backward, self.wl_error)

class FixedQuantizer(nn.Module):
    def __init__(self, wl, fl, mode="stochastic", quantize_backward=True):
        super(FixedQuantizer, self).__init__()
        self.wl = wl
        self.fl = fl
        self.mode = mode
        self.quantize_backward = quantize_backward

    def forward(self, x):
        return quantize_fixed(x, self.wl, self.fl, self.mode,
            self.quantize_backward)

if __name__ == "__main__":
    # import numpy as np
    # lst = []
    # scale = 10
    # target = Variable(-torch.ones(2) * np.random.rand() * scale)
    # # target = Variable(torch.ones(1) * scale)
    # print("Target:%.15f"%target.data[0])

    # wl, fl = 16, 14
    # for i in range(10000):
    #     out = quantize_stochastic_rounding(target, wl, fl, False)
    #     lst.append(out.data[0])

    # print("Quantize(ex):%.15f"%out.data[0])

    # expectation = np.array(lst).mean()
    # print("Expentation :%.15f"%expectation)
    # print("Target      :%.15f"%target.data[0])
    # print("Difference  :%.15f"%(abs(expectation - target.data[0])/2.**(-fl)))


    # import numpy as np
    # lst = []
    # wl, fl = 16, 14
    # scale = 1e-10
    # target = Variable(torch.ones(2) * np.random.rand() * scale, requires_grad=True)
    # input  = Variable(torch.ones(2) * np.random.rand() * scale, requires_grad=True)
    # output = quantize_stochastic_rounding(input, wl, fl, False)
    # loss = F.mse_loss(output, target)
    # # target = Variable(torch.ones(1) * scale)
    # print("Target:%.15f"%target.data[0])
    # print("Input :%.15f"%input.data[0])
    # print("Loss  :%.15f"%loss.data[0])
    # loss.backward()
    # print(input.grad)

    lst = []
    wl, fl = 5, 1
    base = np.sqrt(2.)
    scale = 1
    d = 5
    value = (torch.ones(d) * torch.from_numpy(np.random.rand(d)).float() * scale)
    # value = (torch.ones(d) * torch.from_numpy(np.random.rand(d)).float() * scale).int().float()
    target = Variable(value, requires_grad=False)
    input  = Variable(value, requires_grad=True)
    output = quantize_log(input, wl, fl, base, False)

    print("Input :%s"%input)
    print("Output:%s"%output)

    loss = F.mse_loss(output, target)
    print("Target:%.15f"%target.data[0])
    print("Output:%.15f"%output.data[0])
    print("Loss  :%.15f"%loss.data[0])
    """
    loss.backward()
    print("Gradient (auto):%s"%input.grad)

    gcompt = output - target
    gquant = quantize_log(gcompt, wl, fl, False)
    print("Gradient (manu):%s"%gcompt)
    print("Gradient (qunt):%s"%gquant)
    """

    # import numpy as np
    # lst = []
    # wl, fl = 16, 10
    # scale = 100
    # target = Variable(torch.ones(2) * np.random.rand() * scale, requires_grad=True)
    # input  = Variable(torch.ones(2) * np.random.rand() * scale, requires_grad=True)
    # output = quantize_nearest_rounding(input, wl, fl, False)
    # loss = F.mse_loss(output, target)
    # # target = Variable(torch.ones(1) * scale)
    # print("Target:%.15f"%target.data[0])
    # print("Input :%.15f"%input.data[0])
    # print("Output:%.15f"%output.data[0])
    # print("Loss  :%.15f"%loss.data[0])
    # loss.backward()
    # print(input.grad)

