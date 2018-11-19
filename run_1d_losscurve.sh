#! /bin/bash

# Runnable
# mpirun -n 1 \
#     python plot_surface.py \
#     --mpi --cuda --model vgg9 \
#     --x=-0.5:1.5:401 \
#     --dir_type states \
#     --model_file cifar10/trained_nets/vgg9_sgd_lr=0.1_bs=128_wd=0.0_save_epoch=1/model_300.t7 \
#     --model_file2 cifar10/trained_nets/vgg9_sgd_lr=0.1_bs=8192_wd=0.0_save_epoch=1/model_300.t7 \
#     --plot \
#     --threads 8 \
#     --ngpu 2

mpirun -n 1 \
    python plot_surface.py \
    --mpi --cuda --model vgg9 --x=-1:1:51 \
    --model_file cifar10/trained_nets/vgg9_sgd_lr=0.1_bs=128_wd=0.0_save_epoch=1/model_300.t7 \
    --dir_type weights --xnorm filter --xignore biasbn --plot \
    --threads 8 \
    --ngpu 1

