#! /bin/bash

start_epoch=${1}
end_epoch=${2}
for epoch in `seq ${start_epoch} 20 ${end_epoch}`; do
    echo "Will be training on ${epoch}"
done

for epoch in `seq ${start_epoch} 20 ${end_epoch}`; do
    echo "Now training on ${epoch}"
    # mpirun -n 1 \
    python plot_surface.py \
        --mpi --cuda --model vgg16lp --x=-1:1:51 --y=-1:1:51 \
        --model_file /home/guandao/Projects/SWALP-alpha-test/checkpoint/base/8/sgd/200/checkpoint-${epoch}.pt \
        --dir_type weights --xnorm filter --xignore biasbn --ynorm filter --yignore biasbn --plot \
        --ngpu 1 --threads 8 --batch_size 2048
done
