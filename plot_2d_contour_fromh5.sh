#! /bin/bash

# epoch=${1}
# filename="/home/guandao/Projects/SWALP-alpha-test/checkpoint/base/8/sgd/200/checkpoint-${epoch}.pt_weights_xignore=biasbn_xnorm=filter_yignore=biasbn_ynorm=filter.h5_-1.0_1.0_51_x_-1.0_1.0_51_.h5"

filename=${1}
python plot_2D.py --surf_file $filename --show
