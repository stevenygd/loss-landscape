#! /bin/bash

mpirun -n 1 \
    python plot_surface.py \
    --mpi --cuda --model vgg16fp --x=-1:1:51 \
    --model_file /home/guandao/Projects/SWALP-alpha-test/checkpoint/base/full/sgd/200/checkpoint-300.pt \
    --dir_type weights --xnorm filter --xignore biasbn --plot \
    --threads 8 \
    --ngpu 1

