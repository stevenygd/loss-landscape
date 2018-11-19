#! /bin/bash

epoch=${1}
# mpirun -n 1 \
python plot_surface.py \
    --mpi --cuda --model vgg16lp --x=-1:1:51 \
    --model_file /home/guandao/Projects/SWALP-alpha-test/checkpoint/base/8/sgd/200/checkpoint-${epoch}.pt \
    --dir_type weights --xnorm filter --xignore biasbn --plot \
    --threads 8 \
    --ngpu 1

